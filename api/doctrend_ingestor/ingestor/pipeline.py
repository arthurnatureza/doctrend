# -*- coding: utf-8 -*-
"""
Pipeline de ingestao perene — orquestra um ciclo completo para UM canal.
Adaptado de projeto_modelo/youtube_ingestor/ingestor/pipeline.py (prof. Cassio Pinheiro),
domínio Saúde.

Fluxo de um ciclo:
  descobrir (incremental via watermark)
    -> registra snapshot de metricas (views/likes) de TODOS os videos vistos,
       mesmo os ja ingeridos — alimenta as curvas de velocidade D-1/D+7/D+15
    -> para cada video novo e nao-ingerido (idempotencia):
         captar transcricao   (BRONZE)
         limpar + contrato    (SILVER)
       persiste parquet + atualiza estado SQLite
    -> roda analitico do dominio (GOLD)
    -> avanca o watermark do canal

Rodar o mesmo ciclo duas vezes nao duplica dado.
"""

from __future__ import annotations
import re
import glob
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import duckdb
import pandera.pandas as pa
from pandera.pandas import Column, DataFrameSchema, Check

from .state import StateStore, content_hash
from .discovery import get_discovery, VideoMeta
from .transcript import extrair_transcricao

log = logging.getLogger("ingestor")

STOPWORDS = {
    "entao",
    "olha",
    "ne",
    "tipo",
    "veja",
    "bem",
    "o",
    "a",
    "que",
    "de",
    "e",
    "aqui",
    "isso",
    "na",
    "pratica",
    "voce",
    "para",
}

# Contrato Silver: transcricao limpa por trecho, pronta para o Gold.
SILVER_SCHEMA = DataFrameSchema(
    {
        "video_id": Column(str, nullable=False),
        "ordem": Column(int, Check.ge(0)),
        "texto_limpo": Column(str, Check.str_length(min_value=1)),
        "start": Column(float, Check.ge(0)),
        "duration": Column(float, Check.gt(0)),
        "n_palavras": Column(int, Check.ge(1)),
    },
    coerce=True,
)

# Contrato Silver dos metadados (titulo + descricao + tags). Persistido para
# todo video descoberto, mesmo sem transcricao — assim o Gold ainda enxerga
# algo sobre videos sem legenda disponivel.
METADATA_SCHEMA = DataFrameSchema(
    {
        "video_id": Column(str, nullable=False),
        "texto_limpo": Column(str, Check.str_length(min_value=0)),
        "n_palavras": Column(int, Check.ge(0)),
    },
    coerce=True,
)


def _limpar(texto: str) -> str:
    texto = re.sub(r"[^a-zàáâãéêíóôõúüç\s]", " ", texto.lower())
    return " ".join(t for t in texto.split() if t not in STOPWORDS and len(t) > 2)


def _bronze_silver(
    video_id, trechos
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Retorna (df_valido, df_quarentena) — sempre um dos dois, nunca ambos."""
    df = pd.DataFrame(
        [
            {
                "video_id": video_id,
                "ordem": i,
                "texto": t["text"],
                "start": float(t["start"]),
                "duration": float(t["duration"]),
            }
            for i, t in enumerate(trechos)
        ]
    )
    df["texto_limpo"] = df["texto"].apply(_limpar)
    df = df[df["texto_limpo"].str.len() > 0].copy()
    df["n_palavras"] = df["texto_limpo"].str.split().str.len().fillna(0).astype(int)
    candidato = df[
        ["video_id", "ordem", "texto_limpo", "start", "duration", "n_palavras"]
    ]
    try:
        return SILVER_SCHEMA.validate(candidato), None
    except pa.errors.SchemaError as e:
        quarentena = candidato.copy()
        quarentena["motivo"] = str(e)[:300]
        return None, quarentena


def _persistir(df: pd.DataFrame, dominio: str, video_id: str):
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/silver/dominio={dominio}/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _persistir_quarentena(df: pd.DataFrame, dominio: str, video_id: str):
    """Linhas que falharam o contrato Pandera vao pra ca em vez de sumir —
    rastreabilidade exige saber o que foi descartado e por que (coluna 'motivo')."""
    dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = Path(f"./datalake/silver/dominio={dominio}/_quarentena/dt={dia}")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _metadata_silver(v: VideoMeta) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Titulo + descricao + tags limpos — mesma limpeza da transcricao, so que
    aplicada ao que a Data API ja devolve na descoberta (sem custo extra).
    Retorna (df_valido, df_quarentena) — sempre um dos dois, nunca ambos."""
    texto = " ".join([v.title or "", v.description or "", " ".join(v.tags or [])])
    limpo = _limpar(texto)
    n_palavras = len(limpo.split()) if limpo else 0
    candidato = pd.DataFrame(
        [{"video_id": v.video_id, "texto_limpo": limpo, "n_palavras": n_palavras}]
    )
    try:
        return METADATA_SCHEMA.validate(candidato), None
    except pa.errors.SchemaError as e:
        quarentena = candidato.copy()
        quarentena["motivo"] = str(e)[:300]
        return None, quarentena


def _persistir_metadata(df: pd.DataFrame, dominio: str, video_id: str):
    # Sem particao por dt=: e um "retrato atual" do video, nao um evento —
    # sobrescreve no mesmo arquivo a cada ciclo em vez de acumular duplicata.
    base = Path(f"./datalake/silver/dominio={dominio}/metadata")
    base.mkdir(parents=True, exist_ok=True)
    df.to_parquet(base / f"{video_id}.parquet", index=False)


def _gold(dominio: str, vocabulario: list[str]):
    """Analitico do dominio: densidade de termos-alvo (doencas/temas de saude)
    cruzando transcricao (Silver) e titulo/descricao/tags (metadados) — assim
    videos sem legenda disponivel ainda contribuem com o que sabemos deles."""
    fontes = []
    if glob.glob(f"./datalake/silver/dominio={dominio}/dt=*/*.parquet"):
        fontes.append(
            "SELECT video_id, texto_limpo FROM read_parquet("
            f"'./datalake/silver/dominio={dominio}/dt=*/*.parquet')"
        )
    if glob.glob(f"./datalake/silver/dominio={dominio}/metadata/*.parquet"):
        fontes.append(
            "SELECT video_id, texto_limpo FROM read_parquet("
            f"'./datalake/silver/dominio={dominio}/metadata/*.parquet')"
        )
    if not fontes:
        return pd.DataFrame()

    con = duckdb.connect()
    termos = "', '".join(vocabulario) if vocabulario else "x"
    try:
        textos_cte = f"WITH textos AS ({' UNION ALL '.join(fontes)})"
        out = Path(f"./datalake/gold/dominio={dominio}")
        out.mkdir(parents=True, exist_ok=True)

        gold = con.execute(f"""
            {textos_cte},
                 alvo AS (SELECT UNNEST(['{termos}']) AS termo)
            SELECT a.termo, COUNT(*) AS mencoes,
                   COUNT(DISTINCT textos.video_id) AS videos
            FROM textos JOIN alvo a ON textos.texto_limpo LIKE '%' || a.termo || '%'
            GROUP BY a.termo ORDER BY mencoes DESC
        """).df()
        gold.to_parquet(out / "densidade_termos.parquet", index=False)

        # Quebra por video: quais termos do vocabulario cada video aborda —
        # usado no dashboard para mostrar os temas de um video especifico.
        video_termos = con.execute(f"""
            {textos_cte},
                 alvo AS (SELECT UNNEST(['{termos}']) AS termo)
            SELECT DISTINCT textos.video_id, a.termo
            FROM textos JOIN alvo a ON textos.texto_limpo LIKE '%' || a.termo || '%'
        """).df()
        video_termos.to_parquet(out / "video_termos.parquet", index=False)

        return gold
    finally:
        con.close()


def rodar_ciclo(canal: dict, glob_cfg: dict, store: StateStore) -> dict:
    """Executa um ciclo completo de ingestao para um canal. Idempotente."""
    cid, dom = canal["channel_id"], canal["dominio"]
    vocab = canal.get("vocabulario") or glob_cfg.get("vocabulario", [])
    disc = get_discovery(glob_cfg.get("modo_demo", True))

    watermark = store.get_watermark(cid)
    videos = disc.descobrir(
        cid,
        watermark,
        canal.get("max_videos_por_ciclo", 5),
        glob_cfg.get("janela_descoberta_dias", 30),
    )

    novos, ingeridos, pulados, falhas, max_pub = 0, 0, 0, 0, watermark or ""
    for v in videos:
        store.marcar_descoberto(
            v.video_id, cid, dom, v.published_at, v.title, v.view_count, v.like_count
        )
        store.registrar_snapshot(
            v.video_id, dom, v.published_at, v.view_count, v.like_count, v.comment_count
        )
        max_pub = max(max_pub, v.published_at or "")
        novos += 1

        # Titulo/descricao/tags: persiste sempre, mesmo se a transcricao
        # falhar depois — assim o Gold enxerga algo de todo video descoberto.
        meta_valida, meta_quarentena = _metadata_silver(v)
        if meta_valida is not None:
            _persistir_metadata(meta_valida, dom, v.video_id)
        else:
            _persistir_quarentena(meta_quarentena, dom, f"{v.video_id}_metadata")

        trechos, motivo_falha = extrair_transcricao(
            v.video_id,
            glob_cfg.get("idiomas_legenda", ["pt", "en"]),
            vocab,
            glob_cfg.get("modo_demo", True),
        )
        if not trechos:
            store.marcar_falha(v.video_id, motivo_falha or "sem legenda")
            falhas += 1
            continue

        texto_total = " ".join(t["text"] for t in trechos)
        h = content_hash(texto_total)
        if store.ja_ingerido(v.video_id, h):  # idempotencia
            pulados += 1
            continue
        try:
            df_valido, df_quarentena = _bronze_silver(v.video_id, trechos)
            if df_valido is not None:
                _persistir(df_valido, dom, v.video_id)
                store.marcar_ingerido(v.video_id, h, len(df_valido))
                ingeridos += 1
            else:
                _persistir_quarentena(df_quarentena, dom, v.video_id)
                store.marcar_falha(v.video_id, "contrato Silver invalido (quarentena)")
                falhas += 1
        except Exception as e:
            store.marcar_falha(v.video_id, e)
            falhas += 1

    if novos:
        store.update_watermark(cid, max_pub, ingeridos)
    _gold(dom, vocab)

    res = {
        "canal": canal["nome"],
        "descobertos": novos,
        "ingeridos": ingeridos,
        "pulados_idempotencia": pulados,
        "falhas": falhas,
    }
    log.info("ciclo %s -> %s", canal["nome"], res)
    return res
