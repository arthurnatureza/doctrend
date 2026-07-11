# -*- coding: utf-8 -*-
"""
Estado de ingestao em SQLite — a fonte da verdade do pipeline.
Adaptado de projeto_modelo/youtube_ingestor/ingestor/state.py (prof. Cassio Pinheiro).

Responde as tres perguntas do engenheiro de dados:
  1. O que ja ingeri?                -> tabela ingestion_state (PK = video_id)
  2. O que mudou desde a ultima vez? -> watermark por canal (max publishedAt)
  3. Como evito duplicar/corromper?  -> UPSERT idempotente + content_hash
"""

from __future__ import annotations
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS ingestion_state (
    video_id        TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL,
    dominio         TEXT NOT NULL,
    published_at    TEXT,                 -- ISO 8601 (watermark)
    title           TEXT,
    status          TEXT NOT NULL,        -- DISCOVERED|INGESTED|FAILED|SKIPPED
    content_hash    TEXT,                 -- hash da transcricao (detecta mudanca)
    transcript_len  INTEGER DEFAULT 0,
    view_count      INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    error           TEXT,
    discovered_at   TEXT NOT NULL,
    ingested_at     TEXT,
    attempts        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS channel_watermark (
    channel_id          TEXT PRIMARY KEY,
    last_published_at   TEXT,             -- maior publishedAt ja processado
    last_run_at         TEXT,
    videos_total        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_state_channel ON ingestion_state(channel_id);
CREATE INDEX IF NOT EXISTS idx_state_status  ON ingestion_state(status);

-- Uma linha por (video, dia em que foi observado): permite comparar
-- visualizacoes/likes do mesmo video em D-1, D+7, D+15 etc.
CREATE TABLE IF NOT EXISTS metrics_snapshot (
    video_id        TEXT NOT NULL,
    dominio         TEXT NOT NULL,
    captured_at     TEXT NOT NULL,        -- ISO 8601, momento da coleta
    published_at    TEXT,
    view_count      INTEGER DEFAULT 0,
    like_count      INTEGER DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    PRIMARY KEY (video_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_video ON metrics_snapshot(video_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


class StateStore:
    def __init__(self, db_path: str = "./datalake/control/ingestion.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(DDL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- WATERMARK: incrementalidade -------------------------------------
    def get_watermark(self, channel_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT last_published_at FROM channel_watermark WHERE channel_id=?",
                (channel_id,),
            ).fetchone()
            return row["last_published_at"] if row else None

    def update_watermark(self, channel_id: str, published_at: str, novos: int) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO channel_watermark
                    (channel_id, last_published_at, last_run_at, videos_total)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    last_published_at = MAX(excluded.last_published_at,
                                            channel_watermark.last_published_at),
                    last_run_at       = excluded.last_run_at,
                    videos_total      = channel_watermark.videos_total + excluded.videos_total
            """,
                (channel_id, published_at or "", _now(), novos),
            )

    # --- IDEMPOTENCIA: ja processei este video? ---------------------------
    def ja_ingerido(self, video_id: str, novo_hash: str | None = None) -> bool:
        """True se o video ja esta INGESTED e o conteudo nao mudou."""
        with self._conn() as c:
            row = c.execute(
                "SELECT status, content_hash FROM ingestion_state WHERE video_id=?",
                (video_id,),
            ).fetchone()
        if not row or row["status"] != "INGESTED":
            return False
        if novo_hash is not None and row["content_hash"] != novo_hash:
            return False  # legenda mudou -> reprocessa
        return True

    def marcar_descoberto(
        self,
        video_id,
        channel_id,
        dominio,
        published_at,
        title,
        view_count=0,
        like_count=0,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO ingestion_state
                    (video_id, channel_id, dominio, published_at, title,
                     status, discovered_at, view_count, like_count)
                VALUES (?, ?, ?, ?, ?, 'DISCOVERED', ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    view_count = excluded.view_count,
                    like_count = excluded.like_count
            """,
                (
                    video_id,
                    channel_id,
                    dominio,
                    published_at,
                    title,
                    _now(),
                    view_count,
                    like_count,
                ),
            )

    def marcar_ingerido(self, video_id, c_hash, t_len) -> None:
        with self._conn() as c:
            c.execute(
                """
                UPDATE ingestion_state
                SET status='INGESTED', content_hash=?, transcript_len=?,
                    ingested_at=?, attempts=attempts+1, error=NULL
                WHERE video_id=?
            """,
                (c_hash, t_len, _now(), video_id),
            )

    def marcar_falha(self, video_id, erro) -> None:
        with self._conn() as c:
            c.execute(
                """
                UPDATE ingestion_state
                SET status='FAILED', error=?, attempts=attempts+1
                WHERE video_id=?
            """,
                (str(erro)[:300], video_id),
            )

    def registrar_snapshot(
        self, video_id, dominio, published_at, view_count, like_count, comment_count
    ) -> None:
        """Grava uma leitura de metricas do video no momento atual. Chamar em
        toda descoberta (mesmo de video ja ingerido) para acumular a serie
        temporal usada nas curvas de velocidade de crescimento (D-1/D+7/D+15)."""
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO metrics_snapshot
                    (video_id, dominio, captured_at, published_at,
                     view_count, like_count, comment_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, captured_at) DO NOTHING
            """,
                (
                    video_id,
                    dominio,
                    _now(),
                    published_at,
                    view_count,
                    like_count,
                    comment_count,
                ),
            )

    # --- Observabilidade ----------------------------------------------------
    def resumo(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) n FROM ingestion_state GROUP BY status"
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}
