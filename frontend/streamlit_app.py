# -*- coding: utf-8 -*-
"""Dashboard DocTrend — insights de engajamento por tema de saude no YouTube.

Le direto do datalake gerado pelo ingestor (api/): Gold (Parquet, densidade de
termos) e o estado de controle (SQLite: watermark, contagem por status,
snapshots de metricas ao longo do tempo).
"""

from __future__ import annotations
import glob
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DATALAKE = Path("./datalake")
CONTROL_DB = DATALAKE / "control" / "ingestion.db"
GOLD_GLOB = str(DATALAKE / "gold" / "dominio=*" / "densidade_termos.parquet")
VIDEO_TERMOS_GLOB = str(DATALAKE / "gold" / "dominio=*" / "video_termos.parquet")
SILVER_GLOB = str(DATALAKE / "silver" / "dominio=*" / "**" / "*.parquet")

st.set_page_config(
    page_title="DocTrend — Insights de Saude", page_icon="🩺", layout="wide"
)


@st.cache_data(ttl=60)
def carregar_gold() -> pd.DataFrame:
    arquivos = glob.glob(GOLD_GLOB, recursive=True)
    if not arquivos:
        return pd.DataFrame(columns=["termo", "mencoes", "videos"])
    return pd.concat((pd.read_parquet(f) for f in arquivos), ignore_index=True)


@st.cache_data(ttl=60)
def carregar_video_termos() -> pd.DataFrame:
    arquivos = glob.glob(VIDEO_TERMOS_GLOB, recursive=True)
    if not arquivos:
        return pd.DataFrame(columns=["video_id", "termo"])
    return pd.concat((pd.read_parquet(f) for f in arquivos), ignore_index=True)


@st.cache_data(ttl=60)
def carregar_estado() -> dict:
    if not CONTROL_DB.exists():
        return {"resumo": {}, "watermarks": pd.DataFrame(), "snapshots": pd.DataFrame()}
    con = sqlite3.connect(CONTROL_DB)
    try:
        resumo = (
            pd.read_sql(
                "SELECT status, COUNT(*) n FROM ingestion_state GROUP BY status", con
            )
            .set_index("status")["n"]
            .to_dict()
        )
        watermarks = pd.read_sql("SELECT * FROM channel_watermark", con)
        snapshots = pd.read_sql(
            """
            SELECT s.*, i.title
            FROM metrics_snapshot s
            LEFT JOIN ingestion_state i ON i.video_id = s.video_id
            ORDER BY s.captured_at
            """,
            con,
        )
        return {"resumo": resumo, "watermarks": watermarks, "snapshots": snapshots}
    finally:
        con.close()


gold = carregar_gold()
video_termos = carregar_video_termos()
estado = carregar_estado()
resumo = estado["resumo"]
watermarks = estado["watermarks"]
snapshots = estado["snapshots"]

st.title("🩺 DocTrend — Temas de Saude em Alta no YouTube")
st.caption(
    "Quais doencas e temas de saude mais aparecem nas transcricoes dos "
    "principais canais — e quais geram mais engajamento."
)

ultima_atualizacao = watermarks["last_run_at"].max() if not watermarks.empty else None

col1, col2, col3, col4 = st.columns(4)
col1.metric("Videos ingeridos", int(resumo.get("INGESTED", 0)))
col2.metric("Videos descobertos", sum(resumo.values()) if resumo else 0)
col3.metric("Falhas (sem legenda etc.)", int(resumo.get("FAILED", 0)))
col4.metric("Ultima coleta", ultima_atualizacao[:16] if ultima_atualizacao else "—")

st.divider()

if gold.empty:
    st.info(
        "Ainda sem dados no Gold. Rode `python -m doctrend_ingestor.scheduler "
        "--once` no container `api` (ou aguarde o proximo ciclo agendado)."
    )
else:
    termo_top = gold.sort_values("mencoes", ascending=False).iloc[0]
    st.subheader(f"🔥 Tema mais mencionado: **{termo_top['termo']}**")
    st.caption(
        f"{int(termo_top['mencoes'])} mencoes em {int(termo_top['videos'])} videos distintos"
    )

    left, right = st.columns([2, 1])
    with left:
        st.bar_chart(gold.set_index("termo")["mencoes"].sort_values(ascending=False))
    with right:
        st.dataframe(
            gold.sort_values("mencoes", ascending=False).reset_index(drop=True),
            use_container_width=True,
        )

if not snapshots.empty:
    snapshots["captured_at"] = pd.to_datetime(snapshots["captured_at"])
    snapshots["titulo_exibicao"] = snapshots["title"].fillna(snapshots["video_id"])

    # Um vídeo por linha, com views mais recentes e nº de coletas — ordena do
    # mais visto pro menos visto, que é o mais interessante de olhar primeiro.
    por_video = (
        snapshots.sort_values("captured_at")
        .groupby("video_id")
        .agg(
            titulo=("titulo_exibicao", "last"),
            views_atual=("view_count", "last"),
            n_coletas=("video_id", "count"),
            publicado_em=("published_at", "last"),
        )
        .sort_values("views_atual", ascending=False)
        .reset_index()
    )
else:
    por_video = pd.DataFrame(
        columns=["video_id", "titulo", "views_atual", "n_coletas", "publicado_em"]
    )

st.divider()
st.subheader("🏆 Top 10 vídeos por visualizações")
if por_video.empty:
    st.info("Ainda sem métricas de vídeo coletadas.")
else:
    top10 = por_video.head(10).copy()
    data_pub = pd.to_datetime(top10["publicado_em"], errors="coerce").dt.strftime(
        "%d/%m"
    )
    top10["rótulo"] = (
        top10["titulo"].str.slice(0, 45) + " (" + data_pub.fillna("—") + ")"
    )
    st.bar_chart(top10.set_index("rótulo")["views_atual"])

st.divider()
st.subheader("📈 Velocidade de crescimento (views ao longo do tempo)")
if snapshots.empty:
    st.info("Ainda sem snapshots suficientes para montar curvas de crescimento.")
else:
    opcoes = por_video["video_id"].tolist()
    rotulos = {
        row.video_id: f"{row.titulo[:70]} — {row.views_atual:,} views ({row.n_coletas} coleta(s))"
        for row in por_video.itertuples()
    }
    esquerda, direita = st.columns([2, 1])
    with esquerda:
        escolhido = st.selectbox(
            "Vídeo", opcoes, format_func=lambda vid: rotulos.get(vid, vid)
        )
        serie = (
            snapshots[snapshots["video_id"] == escolhido]
            .sort_values("captured_at")
            .set_index("captured_at")[["view_count", "like_count"]]
        )
        if len(serie) < 2:
            st.caption(
                "⏳ Só há 1 coleta para este vídeo até agora — a curva aparece "
                "como um ponto só. Ela ganha forma conforme os próximos ciclos "
                "agendados rodam (a cada 6h) e novos snapshots se acumulam."
            )
        st.line_chart(serie)
    with direita:
        st.markdown("**Temas abordados neste vídeo**")
        termos_video = (
            video_termos[video_termos["video_id"] == escolhido]["termo"]
            .sort_values()
            .tolist()
            if not video_termos.empty
            else []
        )
        if termos_video:
            st.markdown("\n".join(f"- {t}" for t in termos_video))
        else:
            st.caption(
                "Nenhum termo do vocabulário encontrado no título/descrição/"
                "transcrição deste vídeo ainda."
            )

st.divider()
with st.expander("Como interpretar"):
    st.markdown(
        "- **Mencoes**: quantas vezes o termo aparece nas transcricoes limpas "
        "(camada Silver) dos videos coletados.\n"
        "- **Videos**: quantos videos distintos citam o termo pelo menos uma vez.\n"
        "- **Velocidade**: cada coleta grava um snapshot de views/likes do video; "
        "comparando snapshots (D-1, D+7, D+15...) da pra ver se um tema esta "
        "ganhando ou perdendo tracao."
    )
