# -*- coding: utf-8 -*-
"""
Entrypoint da ingestao perene. Usa APScheduler para agendar CADA canal no
seu proprio intervalo (decisao de negocio definida em config/canais.yaml).
Adaptado de projeto_modelo/youtube_ingestor/scheduler.py (prof. Cassio Pinheiro).

Uso:
  python -m doctrend_ingestor.scheduler            # roda perene (Ctrl+C p/ sair)
  python -m doctrend_ingestor.scheduler --once     # roda 1 ciclo de cada canal e sai
  python -m doctrend_ingestor.scheduler --status   # imprime resumo do estado
"""

from __future__ import annotations
import sys
import logging
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .ingestor.state import StateStore
from .ingestor.pipeline import rodar_ciclo
from .notify import notificar_telegram

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("scheduler")

CONFIG = Path(__file__).parent / "config" / "canais.yaml"


def carregar_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def rodar_ciclo_notificado(canal: dict, glob_cfg: dict, store: StateStore) -> dict:
    """Roda o ciclo normal e manda um resumo pro Telegram (se configurado).
    Notificacao e best-effort: nunca impede o ciclo de rodar nem propaga erro
    de rede do Telegram para o agendador."""
    try:
        res = rodar_ciclo(canal, glob_cfg, store)
    except Exception as e:
        notificar_telegram(f"🔴 DocTrend — {canal['nome']}: ciclo falhou — {e}")
        raise
    emoji = "✅" if res["falhas"] == 0 else "⚠️"
    notificar_telegram(
        f"{emoji} DocTrend — {res['canal']}\n"
        f"descobertos={res['descobertos']} ingeridos={res['ingeridos']} "
        f"falhas={res['falhas']} pulados={res['pulados_idempotencia']}"
    )
    return res


def rodar_uma_vez(cfg: dict, store: StateStore):
    glob = cfg.get("global", {})
    for canal in cfg["canais"]:
        if canal.get("ativo", True):
            rodar_ciclo_notificado(canal, glob, store)


def main():
    cfg = carregar_config()
    store = StateStore()

    if "--status" in sys.argv:
        print("Estado de ingestao:", store.resumo())
        return
    if "--once" in sys.argv:
        log.info("Execucao unica (--once)")
        rodar_uma_vez(cfg, store)
        print("Resumo final:", store.resumo())
        return

    sched = BlockingScheduler(timezone="America/Fortaleza")
    glob = cfg.get("global", {})
    for canal in cfg["canais"]:
        if not canal.get("ativo", True):
            continue
        intervalo = canal.get("intervalo_min", 60)
        sched.add_job(
            rodar_ciclo_notificado,
            IntervalTrigger(minutes=intervalo),
            args=[canal, glob, store],
            id=canal["channel_id"],
            name=canal["nome"],
            max_instances=1,
            coalesce=True,  # nao acumula execucoes atrasadas
        )  # IntervalTrigger ja agenda a 1a corrida em agora + intervalo

        log.info("agendado: %s a cada %d min", canal["nome"], intervalo)

    log.info("Ingestor perene iniciado. Ctrl+C para encerrar.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("encerrando...")


if __name__ == "__main__":
    main()
