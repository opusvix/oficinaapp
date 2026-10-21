"""Dinheiro: conta em Decimal (centavo exato), mostra em real brasileiro.

float erra centavo em soma e divisão (0,1 + 0,2 != 0,3). Parcela e saldo de
caixa não podem errar centavo, então toda conta de dinheiro passa por aqui.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")


def dinheiro(valor) -> Decimal:
    """Qualquer coisa (texto '1.234,56', '12.5', float, None) -> Decimal com 2 casas."""
    if valor is None or valor == "":
        return Decimal("0.00")
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, (int, float)):
        d = Decimal(str(valor))
    else:
        txt = str(valor).strip().replace("R$", "").replace(" ", "")
        if "," in txt:                       # formato brasileiro: 1.234,56
            txt = txt.replace(".", "").replace(",", ".")
        try:
            d = Decimal(txt)
        except InvalidOperation:
            raise ValueError("Valor numérico inválido.")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def moeda(valor, simbolo: bool = True) -> str:
    """Filtro Jinja: 1234.5 -> 'R$ 1.234,50'."""
    try:
        d = dinheiro(valor)
    except ValueError:
        return "—"
    txt = f"{abs(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sinal = "-" if d < 0 else ""
    return f"{sinal}R$ {txt}" if simbolo else f"{sinal}{txt}"


def divide_em_parcelas(total, n: int) -> list[Decimal]:
    """Divide o total em n parcelas que SOMAM o total exato: o resto vai na última.

    100,00 em 3 = 33,33 + 33,33 + 33,34 (e não 33,33 x 3 = 99,99).
    """
    total = dinheiro(total)
    if n < 1:
        raise ValueError("Número de parcelas inválido.")
    base = (total / n).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    parcelas = [base] * (n - 1)
    parcelas.append(total - base * (n - 1))
    return parcelas


def documento(valor) -> str:
    """Filtro Jinja: CPF/CNPJ só com dígitos -> com máscara. Outro formato sai como veio."""
    dig = "".join(c for c in str(valor or "") if c.isdigit())
    if len(dig) == 11:
        return f"{dig[:3]}.{dig[3:6]}.{dig[6:9]}-{dig[9:]}"
    if len(dig) == 14:
        return f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}"
    return str(valor or "")


if __name__ == "__main__":
    assert documento("22333444000181") == "22.333.444/0001-81"
    assert documento("12345678909") == "123.456.789-09"
    assert documento("") == ""
    assert dinheiro("1.234,56") == Decimal("1234.56")
    assert dinheiro("12.5") == Decimal("12.50")
    assert dinheiro(0.1) + dinheiro(0.2) == Decimal("0.30")
    assert moeda(1234.5) == "R$ 1.234,50" and moeda(-30) == "-R$ 30,00" and moeda(None) == "R$ 0,00"
    assert divide_em_parcelas("100", 3) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(divide_em_parcelas("241,00", 7)) == Decimal("241.00")
    print("ok")
