"""Validação server-side do Financeiro (Padrao_Validacao_de_Input, Padrao_Mass_Assignment)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.formato import dinheiro

FORMAS_PAGAMENTO = {
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "cartao_debito": "Cartão de débito",
    "cartao_credito": "Cartão de crédito",
    "boleto": "Boleto",
}
TIPOS_TITULO = {"RECEBER", "PAGAR"}
MAX_PARCELAS = 24


def _data(valor: str | None, campo: str) -> str:
    txt = (valor or "").strip()
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError(f"{campo} inválida.")


def _positivo(valor) -> str:
    v = dinheiro(valor)
    if v <= 0:
        raise ValueError("O valor tem que ser maior que zero.")
    if v > 10_000_000:
        raise ValueError("Valor fora do limite.")
    return str(v)


class TituloIn(BaseModel):
    """Novo título a pagar ou a receber (com parcelas)."""

    model_config = ConfigDict(extra="forbid")

    tipo: str
    descricao: str = Field(min_length=3, max_length=200)
    valor: str
    data_vencimento: str
    parcelas: str | None = "1"
    id_cliente: str | None = None
    fornecedor: str | None = Field(default=None, max_length=200)
    observacoes: str | None = Field(default=None, max_length=1000)

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in TIPOS_TITULO:
            raise ValueError("Tipo inválido.")
        return v

    @field_validator("descricao")
    @classmethod
    def _descricao(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Descreva o título (mínimo 3 caracteres).")
        return v

    @field_validator("valor")
    @classmethod
    def _valor(cls, v: str) -> str:
        return _positivo(v)

    @field_validator("data_vencimento")
    @classmethod
    def _venc(cls, v: str) -> str:
        return _data(v, "Data de vencimento")

    @field_validator("parcelas")
    @classmethod
    def _parcelas(cls, v: str | None) -> str:
        txt = (v or "1").strip()
        if not txt.isdigit() or not 1 <= int(txt) <= MAX_PARCELAS:
            raise ValueError(f"Parcelas: de 1 a {MAX_PARCELAS}.")
        return txt

    @field_validator("id_cliente")
    @classmethod
    def _cliente(cls, v: str | None) -> str | None:
        txt = (v or "").strip()
        if not txt:
            return None
        if not txt.isdigit():
            raise ValueError("Cliente inválido.")
        return txt

    @field_validator("fornecedor", "observacoes")
    @classmethod
    def _texto(cls, v: str | None) -> str | None:
        txt = (v or "").strip()
        return txt or None


class BaixaIn(BaseModel):
    """Baixa (pagamento ou recebimento) de um título."""

    model_config = ConfigDict(extra="forbid")

    forma_pagamento: str
    data_pagamento: str

    @field_validator("forma_pagamento")
    @classmethod
    def _forma(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in FORMAS_PAGAMENTO:
            raise ValueError("Escolha a forma de pagamento.")
        return v

    @field_validator("data_pagamento")
    @classmethod
    def _dt(cls, v: str) -> str:
        return _data(v, "Data do pagamento")


class CaixaValorIn(BaseModel):
    """Valor de abertura, suprimento, sangria ou contagem de fechamento."""

    model_config = ConfigDict(extra="forbid")

    valor: str
    descricao: str | None = Field(default=None, max_length=200)

    @field_validator("valor")
    @classmethod
    def _valor(cls, v: str) -> str:
        d = dinheiro(v)
        if d < 0 or d > 10_000_000:
            raise ValueError("Valor inválido.")
        return str(d)

    @field_validator("descricao")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        txt = (v or "").strip()
        return txt or None


def proximo_mes(d: date, meses: int) -> date:
    """Mesmo dia N meses depois; dia que não existe cai no último do mês (31/01 -> 28/02)."""
    m = d.month - 1 + meses
    ano, mes = d.year + m // 12, m % 12 + 1
    dias_mes = [31, 29 if ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
    return date(ano, mes, min(d.day, dias_mes))


if __name__ == "__main__":
    assert proximo_mes(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert proximo_mes(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert proximo_mes(date(2026, 11, 15), 3) == date(2027, 2, 15)
    t = TituloIn(tipo="receber", descricao="Conserto forno", valor="1.234,56", data_vencimento="2026-10-20")
    assert t.tipo == "RECEBER" and t.valor == "1234.56" and t.parcelas == "1"
    for ruim in ({"valor": "0"}, {"valor": "-5"}, {"parcelas": "25"}, {"data_vencimento": "20/10/2026"}, {"id_perfil": "1"}):
        try:
            TituloIn(**{"tipo": "PAGAR", "descricao": "Aluguel", "valor": "10", "data_vencimento": "2026-10-20", **ruim})
            raise AssertionError(f"aceitou {ruim}")
        except ValueError:
            pass
    print("ok")
