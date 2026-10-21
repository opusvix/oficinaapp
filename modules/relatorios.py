"""Relatórios (Fase 8).

Regras desta fase:
- Quatro relatórios em abas: OS por técnico, tempo médio, peças mais usadas,
  faturamento por cliente. Cada um é tabela (TabelaAvancada: ordenar, filtrar,
  exportar CSV/Excel das linhas visíveis); sem card de KPI (Listagens_sem_KPI).
- Período em DIAS locais (chips padrão, "Mês atual"). Cada relatório diz qual data
  o período corta: abertura da OS, entrega da OS ou pagamento do título.
- Peças e tempo médio contam só OS ENTREGUE: é ali que a peça sai do estoque e
  que o serviço termina. Faturamento conta só título A RECEBER pago.
- Tudo agregado no SQL ou em Python sobre poucas linhas (um mês de oficina), então
  não precisa de exportação em segundo plano (Padrao_Exportacao_em_Segundo_Plano
  é para milhares de linhas).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from core.db import query
from core.formato import dinheiro
from core.tempo import ler_utc, limites_utc
from modules.os import PERIODOS, ROTULOS_STATUS, ORDEM_STATUS, periodo_do_request

relatorios_bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")

ABAS = [
    ("tecnicos", "OS por técnico", "ph-users-three"),
    ("tempo", "Tempo médio", "ph-timer"),
    ("pecas", "Peças mais usadas", "ph-package"),
    ("clientes", "Faturamento por cliente", "ph-currency-circle-dollar"),
]
CORTE = {"tecnicos": "Abertura da OS", "tempo": "Entrega da OS", "pecas": "Entrega da OS",
         "clientes": "Pagamento"}
EM_ANDAMENTO = {"aberta", "avaliacao", "aprovada", "em_andamento"}


def _faixa(de: str | None, ate: str | None) -> tuple[str, str] | None:
    return limites_utc(date.fromisoformat(de), date.fromisoformat(ate)) if de else None


def _horas(a, b) -> float | None:
    ia, ib = ler_utc(a), ler_utc(b)
    if not ia or not ib or ib < ia:
        return None
    return (ib - ia).total_seconds() / 3600


def duracao_texto(horas: float | None) -> str:
    """12.5 -> '12,5 h'; 50 -> '2,1 dias'. Vazio vira '—'."""
    if horas is None:
        return "—"
    if horas < 24:
        return f"{horas:.1f} h".replace(".", ",")
    return f"{horas / 24:.1f} dias".replace(".", ",")


def _media(valores: list) -> float | None:
    v = [x for x in valores if x is not None]
    return sum(v) / len(v) if v else None


# ──────────────────────────────────────────────────────────────────────────────
# Consultas (uma por aba; devolvem linhas + total)
# ──────────────────────────────────────────────────────────────────────────────

def rel_tecnicos(de, ate, id_tecnico, status) -> tuple[list[dict], dict]:
    sql = """SELECT os.id_tecnico, COALESCE(u.nome, 'Sem técnico') AS tecnico, os.status,
                    os.orcamento_status, os.orcamento_valor, os.custo_deslocamento
               FROM ordem_servico os LEFT JOIN usuario u ON u.id = os.id_tecnico
              WHERE os.D_E_L_E_T = 0"""
    params: list = []
    faixa = _faixa(de, ate)
    if faixa:
        sql += " AND os.data_abertura >= ? AND os.data_abertura < ?"
        params += list(faixa)
    if id_tecnico:
        sql += " AND os.id_tecnico = ?"
        params.append(id_tecnico)
    if status:
        sql += " AND os.status = ?"
        params.append(status)
    grupos: dict = defaultdict(lambda: {"total": 0, "andamento": 0, "entregues": 0, "recusadas": 0,
                                         "aprovados": 0, "decididos": 0, "valor": dinheiro(0)})
    for r in query(sql, tuple(params)):
        g = grupos[(r["tecnico"], r["id_tecnico"] or 0)]
        g["total"] += 1
        g["andamento"] += r["status"] in EM_ANDAMENTO
        g["entregues"] += r["status"] == "entregue"
        g["recusadas"] += r["status"] == "recusada"
        if r["orcamento_status"] in ("aprovado", "recusado"):
            g["decididos"] += 1
            g["aprovados"] += r["orcamento_status"] == "aprovado"
        if r["status"] == "entregue":
            g["valor"] += dinheiro(r["orcamento_valor"]) + dinheiro(r["custo_deslocamento"])
    linhas = []
    for (nome, _), g in sorted(grupos.items(), key=lambda kv: (-kv[1]["total"], kv[0][0].lower())):
        taxa = round(100 * g["aprovados"] / g["decididos"]) if g["decididos"] else None
        linhas.append({"tecnico": nome, **g, "taxa": taxa})
    total = {k: sum(l[k] for l in linhas) for k in ("total", "andamento", "entregues", "recusadas")}
    total["valor"] = sum((l["valor"] for l in linhas), dinheiro(0))
    return linhas, total


def rel_tempo(de, ate, id_tecnico) -> tuple[list[dict], dict]:
    sql = """SELECT os.id_tecnico, COALESCE(u.nome, 'Sem técnico') AS tecnico,
                    os.data_abertura, os.data_aprovacao, os.data_entrega
               FROM ordem_servico os LEFT JOIN usuario u ON u.id = os.id_tecnico
              WHERE os.D_E_L_E_T = 0 AND os.status = 'entregue' AND os.data_entrega IS NOT NULL"""
    params: list = []
    faixa = _faixa(de, ate)
    if faixa:
        sql += " AND os.data_entrega >= ? AND os.data_entrega < ?"
        params += list(faixa)
    if id_tecnico:
        sql += " AND os.id_tecnico = ?"
        params.append(id_tecnico)
    grupos: dict = defaultdict(lambda: {"qtd": 0, "aprov": [], "exec": [], "total": []})
    todas = {"aprov": [], "exec": [], "total": []}
    for r in query(sql, tuple(params)):
        g = grupos[r["tecnico"]]
        g["qtd"] += 1
        for k, (a, b) in {"aprov": (r["data_abertura"], r["data_aprovacao"]),
                          "exec": (r["data_aprovacao"], r["data_entrega"]),
                          "total": (r["data_abertura"], r["data_entrega"])}.items():
            h = _horas(a, b)
            g[k].append(h)
            todas[k].append(h)
    linhas = []
    for nome, g in sorted(grupos.items(), key=lambda kv: kv[0].lower()):
        linhas.append({"tecnico": nome, "qtd": g["qtd"],
                       "h_aprov": _media(g["aprov"]), "h_exec": _media(g["exec"]), "h_total": _media(g["total"])})
    total = {"qtd": sum(l["qtd"] for l in linhas), "h_aprov": _media(todas["aprov"]),
             "h_exec": _media(todas["exec"]), "h_total": _media(todas["total"])}
    return linhas, total


def rel_pecas(de, ate, id_tecnico) -> tuple[list[dict], dict]:
    sql = """SELECT it.id_peca, p.codigo, COALESCE(p.descricao, it.descricao) AS descricao,
                    COALESCE(p.unidade, 'UN') AS unidade, it.quantidade, it.preco_unitario, it.id_os
               FROM item_os it
               JOIN ordem_servico os ON os.id = it.id_os
               LEFT JOIN peca p ON p.id = it.id_peca
              WHERE it.D_E_L_E_T = 0 AND os.D_E_L_E_T = 0 AND os.status = 'entregue'"""
    params: list = []
    faixa = _faixa(de, ate)
    if faixa:
        sql += " AND os.data_entrega >= ? AND os.data_entrega < ?"
        params += list(faixa)
    if id_tecnico:
        sql += " AND os.id_tecnico = ?"
        params.append(id_tecnico)
    grupos: dict = {}
    for r in query(sql, tuple(params)):
        # item digitado livre (sem peça do estoque) agrupa pela descrição
        chave = ("p", r["id_peca"]) if r["id_peca"] else ("l", (r["descricao"] or "").strip().lower())
        g = grupos.setdefault(chave, {"codigo": r["codigo"] or "", "descricao": r["descricao"],
                                      "unidade": r["unidade"], "estoque": bool(r["id_peca"]),
                                      "qtd": 0.0, "valor": dinheiro(0), "os": set()})
        q = float(r["quantidade"] or 0)
        g["qtd"] += q
        g["valor"] += dinheiro(dinheiro(r["preco_unitario"]) * dinheiro(q))
        g["os"].add(r["id_os"])
    linhas = sorted(({**g, "n_os": len(g.pop("os"))} for g in grupos.values()),
                    key=lambda l: (-l["qtd"], l["descricao"].lower()))
    total = {"qtd": sum(l["qtd"] for l in linhas), "valor": sum((l["valor"] for l in linhas), dinheiro(0))}
    return linhas, total


def rel_clientes(de, ate) -> tuple[list[dict], dict]:
    sql = """SELECT f.id_cliente, COALESCE(c.razao_social, 'Sem cliente') AS cliente, c.cpf_cnpj,
                    f.valor, f.id_os
               FROM financeiro f LEFT JOIN cliente c ON c.id = f.id_cliente
              WHERE f.D_E_L_E_T = 0 AND f.tipo = 'RECEBER' AND f.status = 'pago'"""
    params: list = []
    if de:
        sql += " AND f.data_pagamento BETWEEN ? AND ?"     # dia local, sem fuso
        params += [de, ate]
    grupos: dict = {}
    for r in query(sql, tuple(params)):
        g = grupos.setdefault(r["id_cliente"] or 0, {"cliente": r["cliente"], "cpf_cnpj": r["cpf_cnpj"] or "",
                                                     "titulos": 0, "os": set(), "recebido": dinheiro(0)})
        g["titulos"] += 1
        g["recebido"] += dinheiro(r["valor"])
        if r["id_os"]:
            g["os"].add(r["id_os"])
    # em aberto é foto de HOJE (não depende do período): quanto o cliente ainda deve
    abertos = {r["id_cliente"] or 0: dinheiro(r["s"]) for r in query(
        "SELECT id_cliente, SUM(valor) AS s FROM financeiro WHERE D_E_L_E_T = 0 AND tipo = 'RECEBER' "
        "AND status = 'aberto' GROUP BY id_cliente")}
    linhas = []
    for id_c, g in grupos.items():
        n_os = len(g.pop("os"))
        linhas.append({**g, "n_os": n_os, "aberto": abertos.get(id_c, dinheiro(0)),
                       "ticket": (g["recebido"] / g["titulos"]).quantize(dinheiro(0)) if g["titulos"] else dinheiro(0)})
    linhas.sort(key=lambda l: (-l["recebido"], l["cliente"].lower()))
    total = {"titulos": sum(l["titulos"] for l in linhas), "n_os": sum(l["n_os"] for l in linhas),
             "recebido": sum((l["recebido"] for l in linhas), dinheiro(0)),
             "aberto": sum((l["aberto"] for l in linhas), dinheiro(0))}
    return linhas, total


# ──────────────────────────────────────────────────────────────────────────────
# Tela
# ──────────────────────────────────────────────────────────────────────────────

@relatorios_bp.route("/")
@login_required
def index():
    if not current_user.pode("relatorios", "ver"):
        abort(403)
    aba = request.args.get("aba") or "tecnicos"
    if aba not in CORTE:
        aba = "tecnicos"
    periodo, de, ate = periodo_do_request(request.args)
    id_tec = request.args.get("tecnico", type=int)
    status = request.args.get("status") or ""
    if status not in ROTULOS_STATUS:
        status = ""
    if aba == "tecnicos":
        linhas, total = rel_tecnicos(de, ate, id_tec, status)
    elif aba == "tempo":
        linhas, total = rel_tempo(de, ate, id_tec)
    elif aba == "pecas":
        linhas, total = rel_pecas(de, ate, id_tec)
    else:
        linhas, total = rel_clientes(de, ate)
    tecnicos = [dict(t) for t in query(
        "SELECT id, nome FROM usuario WHERE D_E_L_E_T = 0 AND id_perfil = 2 ORDER BY nome COLLATE NOCASE")]
    return render_template(
        "relatorios/index.html", aba=aba, abas=ABAS, corte=CORTE[aba], linhas=linhas, total=total,
        periodos=PERIODOS, periodo_sel=periodo, periodo_de=de, periodo_ate=ate,
        tecnico_sel=id_tec, tecnico_rotulo=next((t["nome"] for t in tecnicos if t["id"] == id_tec), "Todos"),
        tecnicos_opcoes=[{"valor": "", "rotulo": "Todos"}] + [{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos],
        status_sel=status, status_rotulo=ROTULOS_STATUS.get(status, "Todos"),
        status_opcoes=[{"valor": "", "rotulo": "Todos"}] + [{"valor": s, "rotulo": ROTULOS_STATUS[s]} for s in ORDEM_STATUS],
        duracao_texto=duracao_texto,
    )
