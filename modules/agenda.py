"""Agenda + Rotas (Fase 8).

Regras desta fase:
- Visita = linha em `agenda` (OS + técnico + início/fim). Início e fim gravados em UTC;
  a tela trabalha em dia/hora LOCAIS (core/tempo).
- Agendar uma OS SEM técnico atribui o técnico a ela (o "click para atribuir").
  OS que já tem técnico só pode ser agendada para ele: trocar o dono de uma OS
  muda quem enxerga fotos e link do cliente, então não acontece de carona.
- Mesmo técnico não pega duas visitas sobrepostas; não se agenda no passado;
  OS entregue/recusada/cancelada não recebe visita.
- Técnico vê só a própria agenda (mesma regra de dono da OS); agendar, concluir e
  cancelar pedem EDITAR em `agenda`.
- Rotas: sem mapa pago nem geocodificação. Agrupa as visitas do dia por cidade e
  bairro, na ordem do primeiro horário de cada bairro, e avisa quando o horário
  marcado obriga a voltar a um bairro já visitado.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from pydantic import ValidationError

from core.auditoria import log_acesso
from core.db import query, query_one, transaction
from core.tempo import agora_utc_texto, hoje_local, limites_utc, local_para_utc_texto, para_local
from modules.validacao_agenda import DURACOES, AgendaIn

agenda_bp = Blueprint("agenda", __name__, url_prefix="/agenda")

STATUS_AGENDA = [("ativos", "Agendados e concluídos"), ("agendado", "Agendados"),
                 ("concluido", "Concluídos"), ("cancelado", "Cancelados"), ("todos", "Todos")]
STATUS_OS_AGENDAVEL = ("aberta", "avaliacao", "aprovada", "em_andamento")
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _exige(acao: str) -> None:
    if not current_user.pode("agenda", acao):
        abort(403)


def _so_a_propria() -> bool:
    """Técnico (qualquer perfil que não é o admin) vê só a própria agenda.

    Mesma régua de modules/os._so_as_proprias: um lugar só decide quem é "gestor".
    """
    return current_user.id_perfil != 1


def _tecnicos() -> list[dict]:
    return [dict(t) for t in query(
        "SELECT id, nome FROM usuario WHERE D_E_L_E_T = 0 AND ativo = 1 AND id_perfil = 2 "
        "ORDER BY nome COLLATE NOCASE")]


def _endereco(v: dict) -> str:
    partes = [" ".join(p for p in (v.get("logradouro"), v.get("numero")) if p),
              v.get("bairro"), " - ".join(p for p in (v.get("cidade"), v.get("uf")) if p)]
    return ", ".join(p for p in partes if p)


def _visitas(ini_utc: str, fim_utc: str, id_tecnico: int | None, status: str) -> list[dict]:
    """Visitas com início em [ini_utc, fim_utc), já com hora local e endereço."""
    sql = """SELECT ag.*, os.patrimonio, os.status AS os_status, os.descricao_inicial,
                    c.razao_social AS cliente, c.logradouro, c.numero, c.bairro, c.cidade, c.uf,
                    u.nome AS tecnico
               FROM agenda ag
               JOIN ordem_servico os ON os.id = ag.id_os
               JOIN cliente c ON c.id = os.id_cliente
               JOIN usuario u ON u.id = ag.id_tecnico
              WHERE ag.D_E_L_E_T = 0 AND ag.data_hora_inicio >= ? AND ag.data_hora_inicio < ?"""
    params: list = [ini_utc, fim_utc]
    if status == "ativos":
        sql += " AND ag.status IN ('agendado', 'concluido')"
    elif status != "todos":
        sql += " AND ag.status = ?"
        params.append(status)
    if id_tecnico:
        sql += " AND ag.id_tecnico = ?"
        params.append(id_tecnico)
    sql += " ORDER BY ag.data_hora_inicio, ag.id"
    saida = []
    for r in query(sql, tuple(params)):
        v = dict(r)
        ini, fim = para_local(v["data_hora_inicio"]), para_local(v["data_hora_fim"])
        v["dia_local"] = ini.date()
        v["hora_ini"] = ini.strftime("%H:%M")
        v["hora_fim"] = fim.strftime("%H:%M") if fim else ""
        v["endereco"] = _endereco(v)
        v["mapa"] = "https://www.google.com/maps/search/?api=1&query=" + quote(v["endereco"]) if v["endereco"] else ""
        saida.append(v)
    return saida


def _sem_agenda(id_tecnico: int | None) -> list[dict]:
    """OS em andamento sem visita marcada: a fila de quem ainda precisa de dia.

    Gestor filtrando um técnico vê também as OS sem técnico (é ali que se atribui);
    o técnico logado vê só as dele (OS sem dono não é dele pra ver).
    """
    sql = f"""SELECT os.id, os.patrimonio, os.status, os.id_tecnico, os.data_abertura,
                     c.razao_social AS cliente, c.logradouro, c.numero, c.bairro, c.cidade, c.uf,
                     u.nome AS tecnico
                FROM ordem_servico os
                JOIN cliente c ON c.id = os.id_cliente
                LEFT JOIN usuario u ON u.id = os.id_tecnico
               WHERE os.D_E_L_E_T = 0 AND os.status IN ({",".join("?" * len(STATUS_OS_AGENDAVEL))})
                 AND NOT EXISTS (SELECT 1 FROM agenda ag WHERE ag.id_os = os.id AND ag.D_E_L_E_T = 0
                                  AND ag.status = 'agendado')"""
    params: list = list(STATUS_OS_AGENDAVEL)
    if id_tecnico and _so_a_propria():
        sql += " AND os.id_tecnico = ?"
        params.append(id_tecnico)
    elif id_tecnico:
        sql += " AND (os.id_tecnico = ? OR os.id_tecnico IS NULL)"
        params.append(id_tecnico)
    sql += " ORDER BY c.cidade COLLATE NOCASE, c.bairro COLLATE NOCASE, os.data_abertura"
    saida = []
    for r in query(sql, tuple(params)):
        o = dict(r)
        o["endereco"] = _endereco(o)
        saida.append(o)
    return saida


def _filtro_tecnico() -> int | None:
    """Técnico logado: sempre ele mesmo (ignora o que vier na URL)."""
    if _so_a_propria():
        return current_user.id
    return request.args.get("tecnico", type=int)


def _rotulo_duracao(minutos: int) -> str:
    h, m = divmod(minutos, 60)
    return f"{m} min" if not h else f"{h}h" + (f"{m:02d}" if m else "")


def _segunda(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


# ──────────────────────────────────────────────────────────────────────────────
# Agenda semanal
# ──────────────────────────────────────────────────────────────────────────────

@agenda_bp.route("/")
@login_required
def semana():
    _exige("ver")
    try:
        base = date.fromisoformat((request.args.get("semana") or "").strip())
    except ValueError:
        base = hoje_local()
    seg = _segunda(base)
    status = request.args.get("status") or "ativos"
    if status not in dict(STATUS_AGENDA):
        status = "ativos"
    id_tec = _filtro_tecnico()
    ini, fim = limites_utc(seg, seg + timedelta(days=6))
    visitas = _visitas(ini, fim, id_tec, status)
    hoje = hoje_local()
    dias = []
    for i in range(7):
        d = seg + timedelta(days=i)
        dias.append({"data": d, "iso": d.isoformat(), "rotulo": f"{DIAS_SEMANA[i]} {d.strftime('%d/%m')}",
                     "hoje": d == hoje, "passado": d < hoje,
                     "visitas": [v for v in visitas if v["dia_local"] == d]})
    tecnicos = _tecnicos()
    sem_agenda = _sem_agenda(id_tec)
    pode_editar = current_user.pode("agenda", "editar")
    return render_template(
        "agenda/semana.html", dias=dias, seg=seg, hoje=hoje,
        semana_ant=(seg - timedelta(days=7)).isoformat(), semana_prox=(seg + timedelta(days=7)).isoformat(),
        titulo_semana=f"{seg.strftime('%d/%m')} a {(seg + timedelta(days=6)).strftime('%d/%m/%Y')}",
        status_sel=status, status_rotulo=dict(STATUS_AGENDA)[status],
        status_opcoes=[{"valor": k, "rotulo": r} for k, r in STATUS_AGENDA],
        tecnico_sel=id_tec, so_a_propria=_so_a_propria(),
        tecnico_rotulo=next((t["nome"] for t in tecnicos if t["id"] == id_tec), "Todos"),
        tecnicos_opcoes=[{"valor": "", "rotulo": "Todos"}] + [{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos],
        tecnicos_form=[{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos],
        os_opcoes=[{"valor": o["id"], "rotulo": f"OS #{o['id']} · {o['patrimonio']} · {o['cliente']}"
                                                + (f" · {o['bairro']}" if o["bairro"] else ""),
                    "tecnico": o["id_tecnico"] or ""} for o in sem_agenda],
        sem_agenda=sem_agenda, duracoes=[{"valor": str(d), "rotulo": _rotulo_duracao(d)} for d in sorted(DURACOES)], pode_editar=pode_editar,
        total_semana=len(visitas),
    )


@agenda_bp.route("/agendar", methods=["POST"])
@login_required
def agendar():
    _exige("editar")
    campos = ("id_os", "id_tecnico", "data", "hora", "duracao", "observacoes")
    volta = request.form.get("semana") or ""
    try:
        dados = AgendaIn(**{k: (request.form.get(k) or "").strip() for k in campos})
    except ValidationError as exc:
        flash("Visita não agendada: " + "; ".join(str(e.get("msg", "")).replace("Value error, ", "")
                                                   for e in exc.errors()), "erro")
        return redirect(url_for("agenda.semana", semana=volta))
    erro = None
    if _so_a_propria() and int(dados.id_tecnico) != current_user.id:
        # técnico com EDITAR (se o admin liberar na matriz) agenda só pra si
        flash("Você só pode agendar visitas para você.", "erro")
        return redirect(url_for("agenda.semana", semana=volta))
    dia = date.fromisoformat(dados.data)
    h, m = map(int, dados.hora.split(":"))
    inicio_local = datetime.combine(dia, time(h, m))
    ini_utc = local_para_utc_texto(dia, time(h, m))
    fim_local = inicio_local + timedelta(minutes=int(dados.duracao))
    fim_utc = local_para_utc_texto(fim_local.date(), fim_local.time())
    with transaction() as db:
        os_row = db.execute("SELECT id, status, id_tecnico, patrimonio FROM ordem_servico "
                            "WHERE id = ? AND D_E_L_E_T = 0", (int(dados.id_os),)).fetchone()
        tec = db.execute("SELECT id, nome FROM usuario WHERE id = ? AND id_perfil = 2 AND ativo = 1 "
                         "AND D_E_L_E_T = 0", (int(dados.id_tecnico),)).fetchone()
        if os_row is None:
            erro = "OS não encontrada."
        elif os_row["status"] not in STATUS_OS_AGENDAVEL:
            erro = "OS entregue ou recusada não recebe visita."
        elif tec is None:
            erro = "Técnico não encontrado."
        elif os_row["id_tecnico"] and os_row["id_tecnico"] != tec["id"]:
            dono = db.execute("SELECT nome FROM usuario WHERE id = ?", (os_row["id_tecnico"],)).fetchone()
            erro = f"Esta OS é de {dono['nome'] if dono else 'outro técnico'}: agende para ele."
        elif ini_utc < agora_utc_texto():
            erro = "Não dá para agendar no passado."
        elif db.execute("SELECT 1 FROM agenda WHERE id_os = ? AND status = 'agendado' AND D_E_L_E_T = 0",
                        (os_row["id"],)).fetchone():
            erro = "Esta OS já tem visita marcada. Cancele a anterior para remarcar."
        else:
            choque = db.execute(
                """SELECT ag.data_hora_inicio, os.patrimonio FROM agenda ag
                     JOIN ordem_servico os ON os.id = ag.id_os
                    WHERE ag.id_tecnico = ? AND ag.status = 'agendado' AND ag.D_E_L_E_T = 0
                      AND ag.data_hora_inicio < ? AND ag.data_hora_fim > ?""",
                (tec["id"], fim_utc, ini_utc)).fetchone()
            if choque:
                erro = (f"{tec['nome']} já tem visita nesse horário "
                        f"({choque['patrimonio']} às {para_local(choque['data_hora_inicio']).strftime('%H:%M')}).")
        if erro is None:
            if not os_row["id_tecnico"]:
                # Atribuição: a trava no WHERE impede que dois agendamentos simultâneos
                # deem a mesma OS a técnicos diferentes.
                cur = db.execute("UPDATE ordem_servico SET id_tecnico = ? WHERE id = ? AND id_tecnico IS NULL",
                                 (tec["id"], os_row["id"]))
                if cur.rowcount != 1:
                    erro = "A OS acabou de ganhar outro técnico. Recarregue a página."
            if erro is None:
                db.execute(
                    """INSERT INTO agenda (id_tecnico, id_os, data_hora_inicio, data_hora_fim, status, observacoes)
                       VALUES (?, ?, ?, ?, 'agendado', ?)""",
                    (tec["id"], os_row["id"], ini_utc, fim_utc, dados.observacoes))
    if erro:
        flash(erro, "erro")
    else:
        log_acesso("AGENDA_CRIADA", current_user.id, f"os={dados.id_os} tecnico={dados.id_tecnico} inicio={ini_utc}")
        flash(f"Visita marcada: {dia.strftime('%d/%m')} às {dados.hora}.", "sucesso")
    return redirect(url_for("agenda.semana", semana=dados.data if not erro else volta,
                            tecnico=request.form.get("filtro_tecnico") or None))


def _muda_status(id_agenda: int, novo: str, acao_log: str, msg: str):
    _exige("editar")
    volta = request.form.get("semana") or ""
    sql = "UPDATE agenda SET status = ? WHERE id = ? AND status = 'agendado' AND D_E_L_E_T = 0"
    params: tuple = (novo, id_agenda)
    if _so_a_propria():          # técnico com EDITAR mexe só nas visitas dele (Padrao_IDOR)
        sql += " AND id_tecnico = ?"
        params += (current_user.id,)
    with transaction() as db:
        cur = db.execute(sql, params)
    if cur.rowcount == 1:
        log_acesso(acao_log, current_user.id, f"agenda={id_agenda}")
        flash(msg, "sucesso")
    else:
        flash("Só visita agendada pode mudar.", "erro")
    return redirect(url_for("agenda.semana", semana=volta, tecnico=request.form.get("filtro_tecnico") or None))


@agenda_bp.route("/<int:id_agenda>/concluir", methods=["POST"])
@login_required
def concluir(id_agenda: int):
    return _muda_status(id_agenda, "concluido", "AGENDA_CONCLUIDA", "Visita concluída.")


@agenda_bp.route("/<int:id_agenda>/cancelar", methods=["POST"])
@login_required
def cancelar(id_agenda: int):
    return _muda_status(id_agenda, "cancelado", "AGENDA_CANCELADA", "Visita cancelada. A OS volta para a fila sem agenda.")


# ──────────────────────────────────────────────────────────────────────────────
# Rotas do dia
# ──────────────────────────────────────────────────────────────────────────────

# escada: rota por bairro, sem distância real. Volta pra geocodificação (CEP -> lat/lng) e
# ordem por vizinho mais próximo se a oficina passar de ~8 visitas/dia por técnico.
def sugerir_rota(visitas: list[dict]) -> dict:
    """Agrupa por (cidade, bairro), grupos na ordem do 1º horário, visitas por horário.

    Devolve as paradas numeradas, quantas trocas de bairro o horário marcado faz e
    quantas a ordem sugerida faz (se a marcada fizer mais, tem volta a bairro já visitado).
    """
    def chave(v):
        return ((v.get("cidade") or "").strip().lower(), (v.get("bairro") or "").strip().lower())

    grupos: dict[tuple, list[dict]] = {}
    for v in sorted(visitas, key=lambda x: x["data_hora_inicio"]):
        grupos.setdefault(chave(v), []).append(v)
    paradas = [v for g in grupos.values() for v in g]   # dict mantém a ordem do 1º horário

    def trocas(lista):
        return sum(1 for a, b in zip(lista, lista[1:]) if chave(a) != chave(b))

    marcada = sorted(visitas, key=lambda x: x["data_hora_inicio"])
    blocos = [{"cidade": g[0].get("cidade") or "Sem cidade", "bairro": g[0].get("bairro") or "Sem bairro",
               "visitas": g} for g in grupos.values()]
    return {"paradas": paradas, "blocos": blocos,
            "trocas_marcada": trocas(marcada), "trocas_sugerida": trocas(paradas)}


def _link_rota(paradas: list[dict]) -> str:
    """Link do Google Maps com as paradas em ordem (o Maps aceita até 9 intermediárias)."""
    enderecos: list[str] = []
    for p in paradas:   # duas OS no mesmo cliente = uma parada só
        if p["endereco"] and (not enderecos or enderecos[-1] != p["endereco"]):
            enderecos.append(p["endereco"])
    enderecos = enderecos[:10]
    if not enderecos:
        return ""
    url = "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=" + quote(enderecos[-1])
    if len(enderecos) > 1:
        url += "&waypoints=" + quote("|".join(enderecos[:-1]))
    return url


@agenda_bp.route("/rotas")
@login_required
def rotas():
    _exige("ver")
    try:
        dia = date.fromisoformat((request.args.get("data") or "").strip())
    except ValueError:
        dia = hoje_local()
    id_tec = _filtro_tecnico()
    ini, fim = limites_utc(dia, dia)
    visitas = _visitas(ini, fim, id_tec, "agendado")
    tecnicos = _tecnicos()
    por_tecnico = []
    for t in tecnicos:
        dele = [v for v in visitas if v["id_tecnico"] == t["id"]]
        if dele:
            rota = sugerir_rota(dele)
            rota.update(tecnico=t["nome"], link=_link_rota(rota["paradas"]))
            por_tecnico.append(rota)
    # fila sem agenda agrupada por bairro: ajuda a montar o dia seguinte
    fila: dict[str, list[dict]] = {}
    for o in _sem_agenda(id_tec):
        fila.setdefault(f"{o['bairro'] or 'Sem bairro'} · {o['cidade'] or 'Sem cidade'}", []).append(o)
    return render_template(
        "agenda/rotas.html", dia=dia, dia_iso=dia.isoformat(), hoje=hoje_local(),
        dia_ant=(dia - timedelta(days=1)).isoformat(), dia_prox=(dia + timedelta(days=1)).isoformat(),
        por_tecnico=por_tecnico, fila=sorted(fila.items(), key=lambda kv: (-len(kv[1]), kv[0])),
        tecnico_sel=id_tec, so_a_propria=_so_a_propria(),
        tecnico_rotulo=next((t["nome"] for t in tecnicos if t["id"] == id_tec), "Todos"),
        tecnicos_opcoes=[{"valor": "", "rotulo": "Todos"}] + [{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos],
    )
