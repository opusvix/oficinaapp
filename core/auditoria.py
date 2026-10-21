"""Auditoria em logs_acesso (Principios, Padrao_Logging_Estruturado).

Eventos: LOGIN, LOGIN_FALHA, LOGIN_BLOQUEADO, LOGIN_ISENCAO_LOCKOUT, LOGOUT,
SESSAO_EXPIRADA, TROCA_SENHA, ACESSO_NEGADO_IDOR.

Regra: senha, token e CPF NUNCA entram no detalhe.
Não chamar dentro de `with transaction()`: o commit daqui fecharia a transação alheia.
"""
from __future__ import annotations

import time
from typing import Optional

from flask import current_app, has_request_context, request

from core.db import get_db


def log_acesso(acao: str, id_usuario: Optional[int] = None, detalhe: str = "") -> None:
    # remote_addr já vem corrigido pelo ProxyFix (core.security.get_client_ip faz o mesmo)
    ip = request.remote_addr if has_request_context() else None
    try:
        db = get_db()
        db.execute(
            "INSERT INTO logs_acesso (id_usuario, acao, detalhe, ip, quando) VALUES (?, ?, ?, ?, ?)",
            (id_usuario, acao, (detalhe or "")[:300], ip, int(time.time())),
        )
        db.commit()
    except Exception:
        # Auditoria que falha não pode derrubar o login; o erro fica no log do app
        current_app.logger.exception("LOG_ACESSO_FALHOU acao=%s", acao)
    # Além da linha no banco (audit), o mesmo evento vira linha JSON no stdout
    # (application log). detalhe pode conter e-mail: log_event redige.
    from core.applog import log_event
    log_event(acao, user_id=id_usuario, detalhe=(detalhe or None))
