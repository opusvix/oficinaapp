"""Validação server-side do cadastro de usuários (Padrao_Validacao_de_Input, Padrao_Mass_Assignment)."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERFIL_CLIENTE = 3   # cliente entra pelo link público da OS, nunca com login


class UsuarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str
    email: str
    id_perfil: str

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        if not 3 <= len(v) <= 150:
            raise ValueError("Nome: de 3 a 150 caracteres.")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.lower()
        if len(v) > 150 or not EMAIL_RE.match(v):
            raise ValueError("E-mail inválido.")
        return v

    @field_validator("id_perfil")
    @classmethod
    def _perfil(cls, v: str) -> str:
        if not v.isdigit() or int(v) <= 0:
            raise ValueError("Escolha o perfil.")
        if int(v) == PERFIL_CLIENTE:
            raise ValueError("Cliente não tem login: ele usa o link da OS.")
        return v


if __name__ == "__main__":
    assert UsuarioIn(nome="Ana Técnica", email=" Ana@Oficina.com ", id_perfil="2").email == "ana@oficina.com"
    for ruim in ({"email": "ana"}, {"nome": "A"}, {"id_perfil": "3"}, {"id_perfil": "x"}):
        try:
            UsuarioIn(**{**dict(nome="Ana", email="a@b.co", id_perfil="2"), **ruim})
        except ValueError:
            continue
        raise AssertionError(f"aceitou {ruim}")
    try:
        UsuarioIn(nome="Ana", email="a@b.co", id_perfil="2", ativo="1")
        raise AssertionError("aceitou campo extra")
    except ValueError:
        pass
    print("ok")
