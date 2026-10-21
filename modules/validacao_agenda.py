"""Validação server-side da Agenda (Padrao_Validacao_de_Input, Padrao_Mass_Assignment)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

DURACOES = {30, 60, 90, 120, 180, 240, 480}   # minutos: lista fechada, igual à do modal
HORA_MIN, HORA_MAX = "06:00", "21:00"          # janela de visita (início)


def _inteiro(valor: str | None, campo: str) -> str:
    txt = (valor or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        raise ValueError(f"{campo} inválido.")
    return txt


class AgendaIn(BaseModel):
    """Visita agendada: OS + técnico + dia/hora LOCAIS + duração."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id_os: str
    id_tecnico: str
    data: str
    hora: str
    duracao: str = "60"
    observacoes: str | None = None

    @field_validator("id_os")
    @classmethod
    def _os(cls, v: str) -> str:
        return _inteiro(v, "OS")

    @field_validator("id_tecnico")
    @classmethod
    def _tec(cls, v: str) -> str:
        return _inteiro(v, "Técnico")

    @field_validator("data")
    @classmethod
    def _data(cls, v: str) -> str:
        try:
            return datetime.strptime(v, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValueError("Data inválida.")

    @field_validator("hora")
    @classmethod
    def _hora(cls, v: str) -> str:
        try:
            h = datetime.strptime(v[:5], "%H:%M").strftime("%H:%M")
        except ValueError:
            raise ValueError("Hora inválida.")
        if not HORA_MIN <= h <= HORA_MAX:
            raise ValueError(f"Visita começa entre {HORA_MIN} e {HORA_MAX}.")
        return h

    @field_validator("duracao")
    @classmethod
    def _duracao(cls, v: str) -> str:
        if not (v or "").isdigit() or int(v) not in DURACOES:
            raise ValueError("Duração inválida.")
        return v

    @field_validator("observacoes")
    @classmethod
    def _obs(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if len(v) > 500:
            raise ValueError("Observação: até 500 caracteres.")
        return v or None


if __name__ == "__main__":
    ok = AgendaIn(id_os="3", id_tecnico="2", data="2026-10-21", hora="08:30", duracao="90")
    assert ok.hora == "08:30"
    for ruim in ({"hora": "23:00"}, {"duracao": "45"}, {"id_os": "0"}, {"data": "21/10/2026"}):
        try:
            AgendaIn(**{**dict(id_os="3", id_tecnico="2", data="2026-10-21", hora="08:30"), **ruim})
        except ValueError:
            continue
        raise AssertionError(f"aceitou {ruim}")
    try:
        AgendaIn(id_os="3", id_tecnico="2", data="2026-10-21", hora="08:30", status="concluido")
        raise AssertionError("aceitou campo extra")
    except ValueError:
        pass
    print("ok")
