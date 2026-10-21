"""Validação server-side para Ordens de Serviço (Padrao_Validacao_de_Input)."""
from __future__ import annotations

import re

from pydantic import ConfigDict, BaseModel, Field, field_validator


def digitos(valor: str | None) -> str:
    if valor is None:
        return ""
    return re.sub(r"\D", "", str(valor))


def _opcional(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


class OSIn(BaseModel):
    """Form de abertura/edição de OS validado no servidor."""

    # Campo que não está declarado aqui é recusado, não ignorado (Padrao_Mass_Assignment)
    model_config = ConfigDict(extra="forbid")

    id_cliente: str | None = None
    id_equipamento: str | None = None
    patrimonio: str | None = Field(default=None, max_length=50)
    id_tecnico: str | None = None
    descricao_inicial: str = Field(min_length=3, max_length=2000)
    custo_deslocamento: str | None = Field(default="0")
    status: str | None = Field(default="aberta", max_length=30)

    @field_validator("id_cliente", "id_equipamento", "id_tecnico")
    @classmethod
    def _id_positivo(cls, valor: str | None) -> int | None:
        texto = _opcional(valor)
        if texto is None:
            return None
        try:
            v = int(texto)
        except ValueError:
            raise ValueError("ID inválido.")
        if v <= 0:
            raise ValueError("ID deve ser maior que zero.")
        return v

    @field_validator("patrimonio")
    @classmethod
    def _patrimonio(cls, valor: str | None) -> str | None:
        valor = _opcional(valor)
        if valor:
            v = valor.strip().upper()
            if len(v) < 3:
                raise ValueError("Patrimônio/Tag muito curto (mínimo 3 caracteres).")
            return v
        return None

    @field_validator("descricao_inicial")
    @classmethod
    def _descricao(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 3:
            raise ValueError("Descreva o problema do equipamento (mínimo 3 caracteres).")
        return valor

    @field_validator("custo_deslocamento")
    @classmethod
    def _decimal(cls, valor: str | None) -> str:
        texto = _opcional(valor) or "0"
        texto = texto.replace(".", "").replace(",", ".")
        try:
            float(texto)
        except ValueError:
            raise ValueError("Valor numérico inválido.")
        return texto

    @field_validator("status")
    @classmethod
    def _status(cls, valor: str | None) -> str:
        # OS nasce aberta ou em avaliação. Aprovada/entregue/recusada só pelo
        # fluxo (link do cliente, execução, entrega): aceitar aqui deixava um
        # POST forjado abrir OS já "entregue" (Padrao_Mass_Assignment).
        iniciais = {"aberta", "avaliacao"}
        v = (_opcional(valor) or "aberta").strip().lower()
        if v not in iniciais:
            raise ValueError("Status inicial inválido.")
        return v

    def para_linhas(self) -> dict:
        dados = self.model_dump()
        # orcamento_valor não vem do form: é a soma dos itens (os.recalcula_orcamento)
        for campo in ("custo_deslocamento",):
            if dados.get(campo):
                dados[campo] = dados[campo].replace(",", ".")
        return dados


class ItemOSIn(BaseModel):
    """Item da OS validado no servidor."""

    # Campo que não está declarado aqui é recusado, não ignorado (Padrao_Mass_Assignment)
    model_config = ConfigDict(extra="forbid")

    id_peca: str | None = None
    descricao: str = Field(min_length=2, max_length=200)
    quantidade: str | None = Field(default="1")
    preco_unitario: str | None = Field(default="0")

    @field_validator("id_peca")
    @classmethod
    def _id_peca(cls, valor: str | None) -> int | None:
        texto = _opcional(valor)
        if texto is None:
            return None
        try:
            return int(texto)
        except ValueError:
            raise ValueError("Peça inválida.")

    @field_validator("descricao")
    @classmethod
    def _descricao(cls, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 2:
            raise ValueError("Descreva o item (mínimo 2 caracteres).")
        return valor

    @field_validator("quantidade", "preco_unitario")
    @classmethod
    def _decimal(cls, valor: str | None) -> str:
        texto = _opcional(valor) or "0"
        texto = texto.replace(".", "").replace(",", ".")
        try:
            float(texto)
        except ValueError:
            raise ValueError("Valor numérico inválido.")
        return texto

    def para_linhas(self) -> dict:
        dados = self.model_dump()
        for campo in ("quantidade", "preco_unitario"):
            if dados.get(campo):
                dados[campo] = dados[campo].replace(",", ".")
        return dados
