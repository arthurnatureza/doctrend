# -*- coding: utf-8 -*-
"""Dashboard DocTrend — insights de engajamento por tema de saúde no YouTube.

Lê direto do datalake gerado pelo ingestor (api/): Gold (Parquet, densidade de
termos) e o estado de controle (SQLite: watermark, contagem por status,
snapshots de métricas ao longo do tempo).
"""

from __future__ import annotations
import glob
import os
import sqlite3
from datetime import timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

BRT = timezone(timedelta(hours=-3))  # Brasília não observa horário de verão desde 2019

DATALAKE = Path("./datalake")
CONTROL_DB = DATALAKE / "control" / "ingestion.db"
GOLD_GLOB = str(DATALAKE / "gold" / "dominio=*" / "densidade_termos.parquet")
VIDEO_TERMOS_GLOB = str(DATALAKE / "gold" / "dominio=*" / "video_termos.parquet")
SILVER_GLOB = str(DATALAKE / "silver" / "dominio=*" / "**" / "*.parquet")

st.set_page_config(
    page_title="DocTrend — Insights de Saúde", page_icon="🩺", layout="wide"
)
st.markdown(
    """
    <style>
    html, body, [class^="st-"], [class*=" st-"] { font-size: 1.15rem; }
    h1 { font-size: 2.4rem !important; }
    h2, [data-testid="stMetricValue"] { font-size: 1.9rem !important; }
    h3 { font-size: 1.6rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
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

st.title("🩺 DocTrend — Temas de Saúde em Alta no YouTube")
st.caption(
    "Quais doenças e temas de saúde mais aparecem nas transcrições dos "
    "principais canais — e quais geram mais engajamento."
)

ultima_atualizacao = watermarks["last_run_at"].max() if not watermarks.empty else None
if ultima_atualizacao:
    ultima_atualizacao_brt = (
        pd.to_datetime(ultima_atualizacao, utc=True)
        .tz_convert(BRT)
        .strftime("%d/%m %H:%M")
    )
else:
    ultima_atualizacao_brt = "—"

col1, col2, col3, col4 = st.columns(4)
col1.metric("Vídeos ingeridos", int(resumo.get("INGESTED", 0)))
col2.metric("Vídeos descobertos", sum(resumo.values()) if resumo else 0)
col3.metric("Falhas (sem legenda etc.)", int(resumo.get("FAILED", 0)))
col4.metric("Última coleta (BRT, UTC-3)", ultima_atualizacao_brt)

st.divider()

if gold.empty:
    st.info(
        "Ainda sem dados no Gold. Rode `python -m doctrend_ingestor.scheduler "
        "--once` no container `api` (ou aguarde o próximo ciclo agendado)."
    )
else:
    termo_top = gold.sort_values("mencoes", ascending=False).iloc[0]
    st.subheader(f"🔥 Tema mais mencionado: **{termo_top['termo']}**")
    st.caption(
        f"{int(termo_top['mencoes'])} menções em {int(termo_top['videos'])} vídeos distintos"
    )

    left, right = st.columns([2, 1])
    with left:
        chart_dados = gold.sort_values("mencoes", ascending=False)
        chart = (
            alt.Chart(chart_dados)
            .mark_bar()
            .encode(
                x=alt.X("mencoes:Q", title="Menções"),
                y=alt.Y("termo:N", sort="-x", title="Termo"),
                tooltip=["termo", "mencoes", "videos"],
            )
            .properties(height=420)
            .configure_axis(labelFontSize=16, titleFontSize=18)
        )
        st.altair_chart(chart, width="stretch")
    with right:
        st.dataframe(
            gold.sort_values("mencoes", ascending=False).reset_index(drop=True),
            width="stretch",
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

# Só considera vídeos que já têm pelo menos um termo do vocabulário
# identificado (transcrição ou metadados) — sem isso não há o que analisar.
por_video_com_termo = por_video[por_video["video_id"].isin(video_termos["video_id"])]

st.divider()
st.subheader("🏆 Top 10 vídeos por visualizações")
st.caption("Apenas vídeos com algum tema do vocabulário identificado.")
if por_video_com_termo.empty:
    st.info(
        "Ainda nenhum vídeo com termos do vocabulário identificados — "
        "aguarde o próximo ciclo de coleta."
    )
else:
    top10 = por_video_com_termo.head(10).copy()
    publicado_em = pd.to_datetime(top10["publicado_em"], errors="coerce")
    agora = pd.Timestamp.now(tz="UTC")
    dias_atras = (agora - publicado_em).dt.days

    for rank, row in enumerate(top10.itertuples(), start=1):
        dias = dias_atras.iloc[rank - 1]
        ha_quanto_tempo = (
            f"há {int(dias)} dia(s)" if pd.notna(dias) else "data desconhecida"
        )
        st.markdown(
            f"**{rank}. {row.titulo}** — {ha_quanto_tempo} — "
            f"**{row.views_atual:,}** views"
        )

st.divider()
st.subheader("📈 Velocidade de crescimento (views ao longo do tempo)")
if por_video_com_termo.empty:
    st.info(
        "Ainda nenhum vídeo com termos do vocabulário identificados — "
        "aguarde o próximo ciclo de coleta."
    )
else:
    opcoes = por_video_com_termo["video_id"].tolist()
    rotulos = {
        row.video_id: f"{row.titulo[:70]} — {row.views_atual:,} views ({row.n_coletas} coleta(s))"
        for row in por_video_com_termo.itertuples()
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
        "- **Menções**: quantas vezes o termo aparece nas transcrições limpas "
        "(camada Silver) dos vídeos coletados.\n"
        "- **Vídeos**: quantos vídeos distintos citam o termo pelo menos uma vez.\n"
        "- **Velocidade**: cada coleta grava um snapshot de views/likes do vídeo; "
        "comparando snapshots (D-1, D+7, D+15...) dá pra ver se um tema está "
        "ganhando ou perdendo tração."
    )

st.divider()
st.caption(f"{os.getenv('DEPLOY_LABEL', 'dev')} · v{os.getenv('APP_VERSION', '0.0')}")
