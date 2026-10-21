"""Validação dos parâmetros de segurança editáveis em /admin/seguranca.

Lista fechada de parâmetros: a tela só mexe nestes, e cada um tem faixa própria.
Guardados na tabela configuracao; a leitura ao vivo já existe (core/auth, core/security).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

MODOS_IP = {"off": "Desligado", "monitor": "Só registra", "block": "Barra a blocklist"}


class SegurancaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_timeout_min: str
    max_login_tentativas: str
    lockout_janela_min: str
    ip_protecao_modo: str

    @staticmethod
    def _faixa(v: str, lo: int, hi: int, nome: str) -> str:
        if not v.isdigit() or not lo <= int(v) <= hi:
            raise ValueError(f"{nome}: de {lo} a {hi}.")
        return str(int(v))

    @field_validator("session_timeout_min")
    @classmethod
    def _timeout(cls, v: str) -> str:
        return cls._faixa(v, 0, 1440, "Timeout")   # 0 desliga; teto 24h

    @field_validator("max_login_tentativas")
    @classmethod
    def _tent(cls, v: str) -> str:
        return cls._faixa(v, 1, 50, "Tentativas")

    @field_validator("lockout_janela_min")
    @classmethod
    def _janela(cls, v: str) -> str:
        return cls._faixa(v, 1, 1440, "Janela")

    @field_validator("ip_protecao_modo")
    @classmethod
    def _modo(cls, v: str) -> str:
        if v not in MODOS_IP:
            raise ValueError("Modo de IP inválido.")
        return v


if __name__ == "__main__":
    ok = SegurancaIn(session_timeout_min="0", max_login_tentativas="5",
                     lockout_janela_min="15", ip_protecao_modo="monitor")
    assert ok.session_timeout_min == "0"
    base = dict(session_timeout_min="60", max_login_tentativas="5", lockout_janela_min="15", ip_protecao_modo="off")
    for ruim in ({"session_timeout_min": "-1"}, {"session_timeout_min": "9999"}, {"max_login_tentativas": "0"},
                 {"lockout_janela_min": "x"}, {"ip_protecao_modo": "tudo"}):
        try:
            SegurancaIn(**{**base, **ruim})
        except ValueError:
            continue
        raise AssertionError(f"aceitou {ruim}")
    try:
        SegurancaIn(**base, extra="1")
        raise AssertionError("aceitou campo extra")
    except ValueError:
        pass
    print("ok")
