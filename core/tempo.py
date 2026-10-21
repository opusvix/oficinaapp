"""Hora do sistema numa regra só: o BANCO guarda UTC, a TELA mostra a hora local.

Antes havia duas convenções misturadas: CURRENT_TIMESTAMP do SQLite (UTC) e
datetime.now() (relógio do servidor, que no EasyPanel também costuma ser UTC).
Resultado: entrega às 18:07 aparecia 21:07, e "Hoje" virava amanhã depois das 21h.

Regra:
- gravar: CURRENT_TIMESTAMP no SQL, ou agora_utc_texto() no Python
- comparar: agora_utc() contra o valor lido com ler_utc()
- mostrar: filtros Jinja |data_hora e |data (converte pra APP_FUSO)
- "hoje", "mês atual" e afins: hoje_local()
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo(os.getenv("APP_FUSO", "America/Sao_Paulo"))
except Exception:  # base de fusos ausente (tzdata não instalado)
    # escada: Brasil sem horário de verão desde 2019, então -03:00 fixo é igual
    # a America/Sao_Paulo hoje. Volta pro ZoneInfo se o tzdata faltar de novo.
    FUSO = timezone(timedelta(hours=-3), "BRT")

FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"


def agora_utc() -> datetime:
    """Agora em UTC, sem tzinfo (mesmo formato do CURRENT_TIMESTAMP)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def agora_utc_texto(mais: Optional[timedelta] = None) -> str:
    """Texto pra gravar no banco: 'AAAA-MM-DD HH:MM:SS' em UTC."""
    return (agora_utc() + (mais or timedelta())).strftime(FORMATO_BANCO)


def agora_local() -> datetime:
    return datetime.now(FUSO)


def hoje_local() -> date:
    return agora_local().date()


def ler_utc(valor) -> Optional[datetime]:
    """Valor do banco (texto UTC, com 'T' ou espaço) -> datetime UTC sem tzinfo."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(valor).replace("T", " ")[:19])
    except ValueError:
        return None


def para_local(valor) -> Optional[datetime]:
    dt = ler_utc(valor)
    return dt.replace(tzinfo=timezone.utc).astimezone(FUSO) if dt else None


def data_hora(valor, formato: str = "%d/%m/%Y %H:%M", vazio: str = "—") -> str:
    """Filtro Jinja: UTC do banco -> 'dd/mm/aaaa hh:mm' na hora local."""
    dt = para_local(valor)
    return dt.strftime(formato) if dt else vazio


def so_data(valor, vazio: str = "—") -> str:
    return data_hora(valor, "%d/%m/%Y", vazio)


def limites_utc(de: date, ate: date) -> tuple[str, str]:
    """Dias LOCAIS [de, ate] -> faixa UTC [início, fim) pra comparar com a coluna.

    'Abertura em 19/10' é 19/10 00:00 até 20/10 00:00 em Brasília, que em UTC é
    19/10 03:00 até 20/10 03:00. Sem isso, OS aberta às 22h caía no dia seguinte.
    """
    inicio = datetime.combine(de, time.min, FUSO).astimezone(timezone.utc)
    fim = datetime.combine(ate + timedelta(days=1), time.min, FUSO).astimezone(timezone.utc)
    return inicio.strftime(FORMATO_BANCO), fim.strftime(FORMATO_BANCO)



def local_para_utc_texto(dia: date, hora: time) -> str:
    """Dia + hora LOCAIS (o que o usuário digitou) -> texto UTC pra gravar no banco."""
    return datetime.combine(dia, hora, FUSO).astimezone(timezone.utc).strftime(FORMATO_BANCO)

if __name__ == "__main__":
    # Checagem mínima, roda sem Flask
    assert data_hora("2026-10-19 21:07:10") == "19/10/2026 18:07", data_hora("2026-10-19 21:07:10")
    assert data_hora("2026-10-20 01:30:00") == "19/10/2026 22:30"          # vira o dia em UTC, não no Brasil
    assert so_data("2026-10-20 01:30:00") == "19/10/2026"
    assert local_para_utc_texto(date(2026, 10, 19), time(22, 30)) == "2026-10-20 01:30:00"
    assert data_hora(None) == "—" and data_hora("lixo") == "—"
    assert limites_utc(date(2026, 10, 19), date(2026, 10, 19)) == ("2026-10-19 03:00:00", "2026-10-20 03:00:00")
    assert ler_utc("2026-10-26T21:07:10.123456") == datetime(2026, 10, 26, 21, 7, 10)
    print("ok")
