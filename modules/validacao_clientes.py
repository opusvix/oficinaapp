"""Validação server-side do cadastro de clientes (Padrao_Validacao_de_Input).

3 camadas: form HTML (required/maxlength) -> Pydantic aqui -> banco.
Campo opcional vazio chega como string vazia e vira None. CPF/CNPJ validam
dígito verificador, não só o formato — máscara bonita com número errado não
passa.
"""
from __future__ import annotations

import re

from pydantic import ConfigDict, BaseModel, Field, field_validator

UFFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def digitos(valor: str | None) -> str:
    """Máscara fora, sobra dígito."""
    return re.sub(r"\D", "", valor or "")


def valida_cpf(cpf: str) -> str:
    """Valida os dois dígitos verificadores. Devolve os 11 dígitos."""
    d = digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        raise ValueError("CPF inválido: confira os 11 dígitos.")
    for posicao in (9, 10):
        soma = sum(int(d[i]) * (posicao + 1 - i) for i in range(posicao))
        resto = soma % 11
        verificador = 0 if resto < 2 else 11 - resto
        if int(d[posicao]) != verificador:
            raise ValueError("CPF inválido: confira os dígitos verificadores.")
    return d


def valida_cnpj(cnpj: str) -> str:
    """Valida os dois dígitos verificadores. Devolve os 14 dígitos."""
    d = digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        raise ValueError("CNPJ inválido: confira os 14 dígitos.")
    for pesos, posicao in (((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), 12),
                           ((6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), 13)):
        soma = sum(int(d[i]) * pesos[i] for i in range(posicao))
        resto = soma % 11
        verificador = 0 if resto < 2 else 11 - resto
        if int(d[posicao]) != verificador:
            raise ValueError("CNPJ inválido: confira os dígitos verificadores.")
    return d


def valida_telefone(valor: str) -> str:
    """10 a 13 dígitos: DDD + número (fixo ou celular)."""
    d = digitos(valor)
    if not 10 <= len(d) <= 13:
        raise ValueError("Telefone inválido: use DDD + número "
                         "(ex: 11 3333-4444 ou 11 99999-0000).")
    return d


def valida_email(valor: str) -> str:
    e = valor.strip().lower()
    if not re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", e):
        raise ValueError("E-mail inválido (ex: nome@dominio.com.br).")
    return e


def valida_cep(valor: str) -> str:
    d = digitos(valor)
    if len(d) != 8:
        raise ValueError("CEP inválido: use 8 dígitos (ex: 01310-100).")
    return d


def _opcional(valor) -> str | None:
    """String vazia ou só espaço vira None (campo não preenchido)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


class ClienteIn(BaseModel):
    """Form de cliente validado no servidor."""

    # Campo que não está declarado aqui é recusado, não ignorado (Padrao_Mass_Assignment)
    model_config = ConfigDict(extra="forbid")

    razao_social: str = Field(min_length=2, max_length=200)
    nome_fantasia: str | None = Field(default=None, max_length=200)
    cpf_cnpj: str | None = None
    ie_rg: str | None = Field(default=None, max_length=20)
    email: str | None = None
    telefone1: str | None = None
    telefone2: str | None = None
    cep: str | None = None
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    cidade: str | None = Field(default=None, max_length=100)
    uf: str | None = Field(default=None, max_length=2)
    observacoes: str | None = None

    @field_validator("razao_social")
    @classmethod
    def _razao(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 2:
            raise ValueError("Informe o nome do cliente (mínimo 2 caracteres).")
        return valor

    @field_validator("cpf_cnpj")
    @classmethod
    def _documento(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        if valor is None:
            return None
        d = digitos(valor)
        if len(d) == 11:
            return valida_cpf(d)
        if len(d) == 14:
            return valida_cnpj(d)
        raise ValueError("CPF/CNPJ deve ter 11 dígitos (CPF) ou 14 (CNPJ).")

    @field_validator("email")
    @classmethod
    def _mail(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        return valida_email(valor) if valor else None

    @field_validator("telefone1", "telefone2")
    @classmethod
    def _tel(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        return valida_telefone(valor) if valor else None

    @field_validator("cep")
    @classmethod
    def _cep(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        return valida_cep(valor) if valor else None

    @field_validator("uf")
    @classmethod
    def _uf(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        if valor is None:
            return None
        sigla = valor.upper()
        if sigla not in UFFS:
            raise ValueError("UF inválida: escolha uma das 27 siglas (ex: SP).")
        return sigla

    @field_validator("nome_fantasia", "ie_rg", "logradouro", "numero",
                     "complemento", "bairro", "cidade", "observacoes")
    @classmethod
    def _limpa(cls, valor: str | None) -> str | None:
        return _opcional(valor)

    def para_linhas(self) -> dict:
        """Colunas para INSERT/UPDATE (dígito limpo em doc, tel e CEP)."""
        dados = self.model_dump()
        for campo in ("cpf_cnpj", "telefone1", "telefone2", "cep"):
            if dados.get(campo):
                dados[campo] = digitos(dados[campo])
        return dados
