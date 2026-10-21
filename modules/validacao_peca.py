"""Validação server-side do cadastro de peças (Padrao_Validacao_de_Input)."""
from __future__ import annotations

import re

from pydantic import ConfigDict, BaseModel, Field, field_validator

# Lista fechada (a tela usa a mesma no SelectBusca de estoque/lista.html)
UNIDADES = ("UN", "PC", "CX", "KG", "LT", "M", "ML")


def digitos(valor: str | None) -> str:
    """Remove máscara, sobra dígito."""
    if valor is None:
        return ""
    return re.sub(r"\D", "", str(valor))


def _opcional(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


class PecaIn(BaseModel):
    """Form de peça validado no servidor."""

    # Campo que não está declarado aqui é recusado, não ignorado (Padrao_Mass_Assignment)
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=2, max_length=50)
    descricao: str = Field(min_length=2, max_length=200)
    unidade: str = Field(default="UN", max_length=10)
    preco_custo: str | None = Field(default="0")
    preco_venda: str | None = Field(default="0")
    estoque_atual: str | None = Field(default="0")
    estoque_minimo: str | None = Field(default="0")
    localizacao: str | None = Field(default=None, max_length=100)

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, valor: str) -> str:
        valor = valor.strip().upper()
        if len(valor) < 2:
            raise ValueError("Informe o código da peça (mínimo 2 caracteres).")
        return valor

    @field_validator("descricao")
    @classmethod
    def _descricao(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 2:
            raise ValueError("Informe a descrição da peça (mínimo 2 caracteres).")
        return valor

    @field_validator("unidade")
    @classmethod
    def _unidade(cls, valor: str | None) -> str:
        valor = _opcional(valor) or "UN"
        sigla = valor.upper()
        if sigla not in UNIDADES:
            raise ValueError("Unidade inválida: UN, PC, CX, KG, LT, M ou ML.")
        return sigla

    @field_validator("preco_custo", "preco_venda", "estoque_atual", "estoque_minimo")
    @classmethod
    def _decimal(cls, valor: str | None) -> str:
        texto = _opcional(valor) or "0"
        texto = texto.replace(".", "").replace(",", ".")
        try:
            float(texto)
        except ValueError:
            raise ValueError("Valor numérico inválido.")
        return texto

    @field_validator("localizacao")
    @classmethod
    def _localizacao(cls, valor: str | None) -> str | None:
        return _opcional(valor)

    def para_linhas(self) -> dict:
        """Colunas para INSERT/UPDATE (vírgula decimal convertida para ponto)."""
        dados = self.model_dump()
        for campo in ("preco_custo", "preco_venda", "estoque_atual", "estoque_minimo"):
            if dados.get(campo):
                dados[campo] = dados[campo].replace(",", ".")
        return dados
