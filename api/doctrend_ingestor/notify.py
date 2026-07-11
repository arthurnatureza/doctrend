# -*- coding: utf-8 -*-
"""
Notificacao opcional via Telegram apos cada ciclo de ingestao.

So dispara se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID estiverem no ambiente — sem
eles, e um no-op silencioso (o pipeline nao depende disso pra funcionar). Uma
falha de rede aqui nunca deve derrubar o ciclo de ingestao.
"""

from __future__ import annotations
import os
import json
import logging
import urllib.request

log = logging.getLogger("notify")


def notificar_telegram(mensagem: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": mensagem}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("falha ao notificar Telegram: %s", e)
