"""Início: painel do dia (substitui a tela de conferência do scaffold da Fase 1).

Cada bloco só aparece pra quem pode VER o módulo dele, e cada número é atalho
pra listagem já filtrada (Padrao_KPI_Dashboard: KPI vive em painel, não em
listagem). Técnico vê só as próprias OS e visitas, mesma régua de modules/os.
"""
from __future__ import annotations

from flask import url_for
from flask_login import current_user

from core.db import query, query_one
from core.formato import dinheiro
from core.tempo import hoje_local, limites_utc, para_local

ATIVAS = ("aberta", "avaliacao", "aprovada", "em_andamento")


def _so_proprias() -> bool:
    return current_user.id_perfil != 1


def painel() -> dict:
    kpis: list[dict] = []
    hoje = hoje_local()
    proprio = _so_proprias()

    if current_user.pode("os", "ver"):
        sql = (f"SELECT COUNT(*) FROM ordem_servico WHERE D_E_L_E_T = 0 "
               f"AND status IN ({','.join('?' * len(ATIVAS))})")
        params: tuple = ATIVAS
        if proprio:
            sql += " AND id_tecnico = ?"
            params += (current_user.id,)
        n = query_one(sql, params)[0]
        kpis.append({"rotulo": "OS em aberto", "valor": n, "icone": "ph-wrench", "classe": "ac-info",
                     "legenda": "suas, ainda não entregues" if proprio else "aberta até em andamento",
                     "link": url_for("os.listar", status="ativas", periodo="todos")})

    visitas = []
    if current_user.pode("agenda", "ver"):
        ini, fim = limites_utc(hoje, hoje)
        sql = """SELECT ag.id_os, ag.data_hora_inicio, os.patrimonio, c.razao_social AS cliente,
                        c.bairro, u.nome AS tecnico
                   FROM agenda ag JOIN ordem_servico os ON os.id = ag.id_os
                   JOIN cliente c ON c.id = os.id_cliente JOIN usuario u ON u.id = ag.id_tecnico
                  WHERE ag.D_E_L_E_T = 0 AND ag.status = 'agendado'
                    AND ag.data_hora_inicio >= ? AND ag.data_hora_inicio < ?"""
        params = (ini, fim)
        if proprio:
            sql += " AND ag.id_tecnico = ?"
            params += (current_user.id,)
        for r in query(sql + " ORDER BY ag.data_hora_inicio", params):
            v = dict(r)
            v["hora"] = para_local(v["data_hora_inicio"]).strftime("%H:%M")
            visitas.append(v)
        kpis.append({"rotulo": "Visitas hoje", "valor": len(visitas), "icone": "ph-calendar-check",
                     "classe": "ac-info", "legenda": "agendadas pra hoje",
                     "link": url_for("agenda.rotas")})

    if current_user.pode("contas_receber", "ver"):
        r = query_one("SELECT COUNT(*), SUM(valor) FROM financeiro WHERE D_E_L_E_T = 0 AND tipo = 'RECEBER' "
                      "AND status = 'aberto' AND data_vencimento < ?", (hoje.isoformat(),))
        kpis.append({"rotulo": "A receber vencido", "valor": dinheiro(r[1] or 0), "dinheiro": True,
                     "icone": "ph-warning-circle", "classe": "neg" if r[0] else "ac-fin",
                     "legenda": f"{r[0]} título{'s' if r[0] != 1 else ''}",
                     "link": url_for("financeiro.receber", status="vencido", periodo="todos")})

    if current_user.pode("caixa", "ver"):
        from modules.financeiro import caixa_aberto, resumo_caixa
        cx = caixa_aberto()
        if cx:
            kpis.append({"rotulo": "Caixa aberto", "valor": resumo_caixa(cx["id"])["gaveta"], "dinheiro": True,
                         "icone": "ph-cash-register", "classe": "pos", "legenda": "dinheiro na gaveta",
                         "link": url_for("financeiro.caixa")})
        else:
            kpis.append({"rotulo": "Caixa", "valor": "Fechado", "icone": "ph-cash-register", "classe": "ac-fin",
                         "legenda": "abra pra receber em dinheiro", "link": url_for("financeiro.caixa")})

    if current_user.pode("pecas", "ver"):
        n = query_one("SELECT COUNT(*) FROM peca WHERE D_E_L_E_T = 0 AND estoque_minimo > 0 "
                      "AND estoque_atual <= estoque_minimo")[0]
        kpis.append({"rotulo": "Peças no mínimo", "valor": n, "icone": "ph-package",
                     "classe": "neg" if n else "ac-fat", "legenda": "estoque igual ou abaixo do mínimo",
                     "link": url_for("estoque.listar", baixo=1)})

    return {"kpis": kpis, "visitas": visitas, "ve_agenda": current_user.pode("agenda", "ver"),
            "hoje": hoje, "proprio": proprio}
