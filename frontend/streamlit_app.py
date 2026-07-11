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
GOLD_GLOB = str(DATALAKE / "gold" / "dominio=*" / "*.parquet")
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
            "SELECT * FROM metrics_snapshot ORDER BY captured_at", con
        )
        return {"resumo": resumo, "watermarks": watermarks, "snapshots": snapshots}
    finally:
        con.close()


gold = carregar_gold()
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

st.divider()
st.subheader("📈 Velocidade de crescimento (views ao longo do tempo)")
if snapshots.empty:
    st.info("Ainda sem snapshots suficientes para montar curvas de crescimento.")
else:
    snapshots["captured_at"] = pd.to_datetime(snapshots["captured_at"])
    videos_disponiveis = snapshots["video_id"].unique().tolist()
    escolhido = st.selectbox("Video", videos_disponiveis)
    serie = (
        snapshots[snapshots["video_id"] == escolhido]
        .sort_values("captured_at")
        .set_index("captured_at")[["view_count", "like_count"]]
    )
    st.line_chart(serie)

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
