"""Application log em JSON (Padrao_Logging_Estruturado).

Coisa DIFERENTE do audit log (tabela logs_acesso, core/auditoria): aquele é o
registro legal de quem fez o quê; este é a linha JSON no stdout, pra
observabilidade (o EasyPanel captura o stdout do container).

Uma linha JSON por evento, com campos fixos (timestamp, level, event, user_id,
ip, request_id, path, method) + extras do evento. Senha, token e e-mail em claro
NUNCA entram: o e-mail é redigido em qualquer campo (checklist: "sem e-mail em
claro"); senha e token nunca são passados pra cá.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import uuid

from flask import Flask, g, has_request_context, request
from flask_login import current_user

from core.tempo import agora_local

_logger = logging.getLogger("oficina.app")
CAMPOS_REQUEST = ("user_id", "ip", "request_id", "path", "method")
_NIVEIS = {"WARNING": "WARN"}   # a nota usa WARN, o logging do Python usa WARNING
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redige_email(texto: str) -> str:
    """'joao@exemplo.com' -> 'j***@exemplo.com'. Não é pra re-identificar, é pra
    não vazar o e-mail no log mantendo o domínio pra diagnóstico."""
    def _troca(m: re.Match) -> str:
        usuario, _, dominio = m.group(0).partition("@")
        return (usuario[0] if usuario else "") + "***@" + dominio
    return _EMAIL_RE.sub(_troca, texto or "")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "timestamp": agora_local().isoformat(timespec="seconds"),
            "level": _NIVEIS.get(record.levelname, record.levelname),
            "event": record.getMessage(),
        }
        base.update(getattr(record, "campos", {}))
        return json.dumps(base, ensure_ascii=False)


def log_event(event: str, level: str = "INFO", **campos) -> None:
    """Emite uma linha JSON. `event` é nome curto padronizado (LOGIN_OK, ...)."""
    if has_request_context():
        campos.setdefault("user_id", getattr(g, "user_id", None))
        campos.setdefault("request_id", getattr(g, "request_id", None))
        campos.setdefault("ip", request.remote_addr)   # já corrigido pelo ProxyFix
        campos.setdefault("path", request.path)
        campos.setdefault("method", request.method)
    else:
        for k in CAMPOS_REQUEST:
            campos.setdefault(k, None)
    # Rede de segurança: redige e-mail que escape em qualquer valor de texto
    campos = {k: (redige_email(v) if isinstance(v, str) else v) for k, v in campos.items()}
    _logger.log(getattr(logging, level, logging.INFO), event, extra={"campos": campos})


def init_applog(app: Flask) -> None:
    """Handler JSON no stdout + request_id/user_id por request.

    Chamar ANTES dos outros init_* para o before_request do request_id rodar
    primeiro: assim qualquer evento já sai com o request_id preenchido.
    """
    if not any(getattr(h, "_oficina", False) for h in _logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        handler._oficina = True  # type: ignore[attr-defined]  (marca pra não duplicar no reload)
        _logger.addHandler(handler)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False  # não repete na raiz (que tem o formato do Flask)

    @app.before_request
    def _contexto_log() -> None:
        g.request_id = uuid.uuid4().hex[:16]
        g.user_id = current_user.id if current_user.is_authenticated else None
