# -*- coding: utf-8 -*-
"""
Descoberta de videos — YouTube Data API v3 com estrategia de cota.
Adaptado de projeto_modelo/youtube_ingestor/ingestor/discovery.py (prof. Cassio Pinheiro).

Cota diaria: 10.000 unidades. Custo por chamada:
  - search.list ............ 100 unidades  (caro — evitar em loop!)
  - playlistItems.list ......   1 unidade
  - videos.list .............   1 unidade
  - channels.list ...........   1 unidade

Estrategia:
  1. channels.list uma vez -> pega a playlist de uploads do canal (UU...).
  2. playlistItems.list a cada ciclo (1 unidade) -> lista uploads recentes.
  3. videos.list em lote de ate 50 IDs (1 unidade) -> metadados ricos.

Em modo_demo=True, nada disso e chamado: geramos metadados sinteticos
deterministicos para rodar sem API key e sem gastar cota.
"""

from __future__ import annotations
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone


@dataclass
class VideoMeta:
    video_id: str
    channel_id: str
    title: str
    description: str
    published_at: str  # ISO 8601 — usado como watermark
    duration_iso: str  # PT#M#S
    view_count: int
    like_count: int
    comment_count: int
    tags: list
    category_id: str
    default_audio_language: str

    def to_row(self) -> dict:
        d = asdict(self)
        d["tags"] = ",".join(self.tags)  # achata p/ parquet/sqlite
        return d


# ---------------------------------------------------------------------------
# Implementacao REAL (Data API v3)
# ---------------------------------------------------------------------------
class YouTubeDiscovery:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self._yt = None

    def _client(self):
        if self._yt is None:
            from googleapiclient.discovery import build

            self._yt = build(
                "youtube", "v3", developerKey=self.api_key, cache_discovery=False
            )
        return self._yt

    def _uploads_playlist(self, channel_id: str) -> str:
        resp = (
            self._client()
            .channels()
            .list(part="contentDetails", id=channel_id)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Canal nao encontrado: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def descobrir(
        self, channel_id: str, since_iso: str | None, max_videos: int, janela_dias: int
    ) -> list[VideoMeta]:
        uploads = self._uploads_playlist(channel_id)
        corte = datetime.now(timezone.utc) - timedelta(days=janela_dias)
        ids, page = [], None
        while len(ids) < max_videos:
            resp = (
                self._client()
                .playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads,
                    maxResults=min(50, max_videos),
                    pageToken=page,
                )
                .execute()
            )
            for it in resp.get("items", []):
                pub = it["contentDetails"].get("videoPublishedAt", "")
                if since_iso and pub <= since_iso:
                    return self._hidratar(channel_id, ids)  # passou do watermark
                if pub and pub >= corte.isoformat():
                    ids.append(it["contentDetails"]["videoId"])
            page = resp.get("nextPageToken")
            if not page:
                break
        return self._hidratar(channel_id, ids[:max_videos])

    def _hidratar(self, channel_id: str, ids: list[str]) -> list[VideoMeta]:
        if not ids:
            return []
        resp = (
            self._client()
            .videos()
            .list(
                part="snippet,statistics,contentDetails",
                id=",".join(ids),
                maxResults=50,
            )
            .execute()
        )
        out = []
        for it in resp.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            cd = it.get("contentDetails", {})
            out.append(
                VideoMeta(
                    video_id=it["id"],
                    channel_id=channel_id,
                    title=sn.get("title", ""),
                    description=sn.get("description", "")[:500],
                    published_at=sn.get("publishedAt", ""),
                    duration_iso=cd.get("duration", ""),
                    view_count=int(st.get("viewCount", 0)),
                    like_count=int(st.get("likeCount", 0)),
                    comment_count=int(st.get("commentCount", 0)),
                    tags=sn.get("tags", []),
                    category_id=sn.get("categoryId", ""),
                    default_audio_language=sn.get("defaultAudioLanguage", ""),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Implementacao DEMO (sintetica, deterministica) — mesma interface
# ---------------------------------------------------------------------------
class DemoDiscovery:
    """Substitui a API real. Gera videos 'novos' a cada ciclo de forma
    deterministica por canal+dia, para exercitar watermark/incrementalidade
    sem API key nem cota."""

    def descobrir(
        self, channel_id: str, since_iso: str | None, max_videos: int, janela_dias: int
    ) -> list[VideoMeta]:
        rng = random.Random(f"{channel_id}-{datetime.now().strftime('%Y%m%d%H')}")
        n = rng.randint(1, max_videos)
        agora = datetime.now(timezone.utc)
        out = []
        for i in range(n):
            pub = agora - timedelta(hours=rng.randint(0, 24 * janela_dias))
            pub_iso = pub.isoformat()
            if since_iso and pub_iso <= since_iso:
                continue  # respeita o watermark, como a API real faria
            vid = f"demo_{channel_id[-4:]}_{pub.strftime('%j%H')}_{i}"
            out.append(
                VideoMeta(
                    video_id=vid,
                    channel_id=channel_id,
                    title=f"Video {i} do canal {channel_id[-4:]}",
                    description="conteudo sintetico para desenvolvimento local",
                    published_at=pub_iso,
                    duration_iso=f"PT{rng.randint(3,40)}M",
                    view_count=rng.randint(1_000, 500_000),
                    like_count=rng.randint(50, 30_000),
                    comment_count=rng.randint(0, 5_000),
                    tags=["demo", "saude", "doctrend"],
                    category_id="26",
                    default_audio_language="pt",
                )
            )
        return out


def get_discovery(modo_demo: bool):
    return DemoDiscovery() if modo_demo else YouTubeDiscovery()
