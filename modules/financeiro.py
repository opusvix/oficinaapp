"""Financeiro + PDV (Fase 7).

Regras desta fase:
- Título = uma linha em `financeiro` (RECEBER ou PAGAR), com parcela/total_parcelas.
  Status: aberto, pago, cancelado, parcelado (o original some da lista de trabalho
  e as parcelas apontam pra ele em id_origem). Nada é apagado (Nunca_DELETE_Fisico).
- Baixa em DINHEIRO exige caixa aberto (o dinheiro passa pela gaveta). Outras formas
  entram no caixa aberto se houver, pro resumo do dia, mas não mexem na gaveta.
- OS ENTREGUE gera o recebível sozinho (orçamento + deslocamento); OS RECUSADA gera
  só o deslocamento, quando houver. Uma vez por OS (idempotente).
- Dinheiro em Decimal (core/formato): parcela soma o total exato.
- Datas: vencimento e pagamento são DIAS locais ('AAAA-MM-DD'); carimbos de caixa em UTC.
- KPI só no dashboard; listagens vão direto pra filtro e tabela (Listagens_sem_KPI).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from pydantic import ValidationError

from core.auditoria import log_acesso
from core.db import query, query_one, transaction
from core.formato import dinheiro, divide_em_parcelas, moeda
from core.tempo import agora_local, agora_utc_texto, hoje_local
from modules.os import PERIODOS, periodo_do_request
from modules.validacao_financeiro import (
    FORMAS_PAGAMENTO,
    BaixaIn,
    CaixaValorIn,
    TituloIn,
    proximo_mes,
)

financeiro_bp = Blueprint("financeiro", __name__, url_prefix="/financeiro")

MODULO_TIPO = {"RECEBER": "contas_receber", "PAGAR": "contas_pagar"}
ROTA_TIPO = {"RECEBER": "receber", "PAGAR": "pagar"}
STATUS_LISTA = [("aberto", "Em aberto"), ("vencido", "Vencidos"), ("pago", "Pagos"),
                ("cancelado", "Cancelados"), ("parcelado", "Parcelados"), ("", "Todos")]


def _exige(modulo: str, acao: str) -> None:
    if not current_user.pode(modulo, acao):
        abort(403)


def _erros(exc: ValidationError) -> dict[str, str]:
    saida: dict[str, str] = {}
    for item in exc.errors():
        campo = str((item.get("loc") or ["formulario"])[0])
        saida[campo] = str(item.get("msg", "")).replace("Value error, ", "")
    return saida


# ──────────────────────────────────────────────────────────────────────────────
# Regras (funções puras sobre a conexão: testáveis e reusadas pela OS)
# ──────────────────────────────────────────────────────────────────────────────

def caixa_aberto(db=None):
    sql = "SELECT * FROM caixa WHERE status = 'aberto' AND D_E_L_E_T = 0"
    return db.execute(sql).fetchone() if db is not None else query_one(sql)


def criar_titulos(db, dados: TituloIn, id_usuario: int | None, id_os: int | None = None) -> list[int]:
    """Cria 1..N parcelas mensais a partir do vencimento informado."""
    n = int(dados.parcelas or "1")
    valores = divide_em_parcelas(dados.valor, n)
    venc0 = date.fromisoformat(dados.data_vencimento)
    ids = []
    for i, valor in enumerate(valores, start=1):
        desc = dados.descricao if n == 1 else f"{dados.descricao} ({i}/{n})"
        cur = db.execute(
            """INSERT INTO financeiro
                   (id_os, tipo, descricao, valor, data_vencimento, status, parcela, total_parcelas,
                    observacoes, id_cliente, fornecedor)
               VALUES (?, ?, ?, ?, ?, 'aberto', ?, ?, ?, ?, ?)""",
            (id_os, dados.tipo, desc, float(valor), proximo_mes(venc0, i - 1).isoformat(), i, n,
             dados.observacoes, int(dados.id_cliente) if dados.id_cliente else None,
             dados.fornecedor if dados.tipo == "PAGAR" else None),
        )
        ids.append(cur.lastrowid)
    return ids


def gerar_recebivel_os(db, id_os: int, evento: str) -> int | None:
    """OS entregue -> recebível de orçamento + deslocamento. OS recusada -> só deslocamento.

    Chamado DENTRO da transação da OS: se o recebível falhar, a entrega também volta.
    Idempotente: se a OS já tem título vivo, não cria outro.
    """
    if db.execute(
        "SELECT 1 FROM financeiro WHERE id_os = ? AND tipo = 'RECEBER' AND D_E_L_E_T = 0 "
        "AND status <> 'cancelado'", (id_os,)
    ).fetchone():
        return None
    os_row = db.execute(
        "SELECT id, id_cliente, patrimonio, orcamento_valor, custo_deslocamento "
        "FROM ordem_servico WHERE id = ?", (id_os,)
    ).fetchone()
    desloc = dinheiro(os_row["custo_deslocamento"])
    if evento == "entregue":
        valor = dinheiro(os_row["orcamento_valor"]) + desloc
        desc = f"OS #{id_os} ({os_row['patrimonio']}): serviço entregue"
    else:
        valor = desloc
        desc = f"OS #{id_os} ({os_row['patrimonio']}): deslocamento (orçamento recusado)"
    if valor <= 0:
        return None
    dados = TituloIn(tipo="RECEBER", descricao=desc, valor=str(valor),
                     data_vencimento=hoje_local().isoformat(),
                     id_cliente=str(os_row["id_cliente"]) if os_row["id_cliente"] else None)
    return criar_titulos(db, dados, None, id_os=id_os)[0]


def baixar_titulo(db, id_titulo: int, baixa: BaixaIn, id_usuario: int) -> str | None:
    """Baixa total do título. Devolve mensagem de erro ou None.

    escada: só baixa TOTAL. Pagamento parcial se resolve parcelando antes; volta
    pra baixa parcial (status 'parcial' já existe no schema) se a oficina pedir.
    """
    tit = db.execute("SELECT * FROM financeiro WHERE id = ? AND D_E_L_E_T = 0", (id_titulo,)).fetchone()
    if tit is None:
        return "Título não encontrado."
    if baixa.data_pagamento > hoje_local().isoformat():
        return "A data do pagamento não pode ser no futuro."
    cx = caixa_aberto(db)
    if baixa.forma_pagamento == "dinheiro" and cx is None:
        return "Dinheiro passa pela gaveta: abra o caixa antes de dar baixa em dinheiro."
    if baixa.forma_pagamento == "dinheiro" and tit["tipo"] == "PAGAR":
        gaveta = resumo_caixa(cx["id"])["gaveta"]   # mesma regra da sangria: gaveta não fica negativa
        if dinheiro(tit["valor"]) > gaveta:
            return f"Não há dinheiro suficiente na gaveta ({moeda(gaveta)}) para pagar {moeda(tit['valor'])}."
    cur = db.execute(
        """UPDATE financeiro
              SET status = 'pago', data_pagamento = ?, forma_pagamento = ?, usuario_baixa = ?,
                  id_caixa = ?
            WHERE id = ? AND status = 'aberto' AND D_E_L_E_T = 0""",
        (baixa.data_pagamento, baixa.forma_pagamento, id_usuario, cx["id"] if cx else None, id_titulo),
    )
    if cur.rowcount != 1:   # dois cliques, ou título que não está mais em aberto
        return "Este título não está mais em aberto."
    if cx is not None:
        db.execute(
            """INSERT INTO caixa_mov (id_caixa, tipo, forma_pagamento, valor, descricao,
                                      id_financeiro, id_usuario, quando)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cx["id"], "RECEBIMENTO" if tit["tipo"] == "RECEBER" else "PAGAMENTO",
             baixa.forma_pagamento, tit["valor"], tit["descricao"], id_titulo, id_usuario,
             agora_utc_texto()),
        )
    return None


def parcelar_titulo(db, id_titulo: int, n: int) -> str | None:
    """Troca um título em aberto por N parcelas mensais (o original vira 'parcelado')."""
    tit = db.execute("SELECT * FROM financeiro WHERE id = ? AND D_E_L_E_T = 0", (id_titulo,)).fetchone()
    if tit is None:
        return "Título não encontrado."
    if not 2 <= n <= 24:
        return "Parcele de 2 a 24 vezes."
    cur = db.execute(
        "UPDATE financeiro SET status = 'parcelado' WHERE id = ? AND status = 'aberto' AND D_E_L_E_T = 0",
        (id_titulo,),
    )
    if cur.rowcount != 1:
        return "Só título em aberto pode ser parcelado."
    dados = TituloIn(tipo=tit["tipo"], descricao=tit["descricao"], valor=str(dinheiro(tit["valor"])),
                     data_vencimento=tit["data_vencimento"] or hoje_local().isoformat(), parcelas=str(n),
                     id_cliente=str(tit["id_cliente"]) if tit["id_cliente"] else None,
                     fornecedor=tit["fornecedor"])
    ids = criar_titulos(db, dados, None, id_os=tit["id_os"])
    db.execute(f"UPDATE financeiro SET id_origem = ? WHERE id IN ({','.join('?' * len(ids))})",
               (id_titulo, *ids))
    return None


def resumo_caixa(id_caixa: int) -> dict:
    cx = query_one("SELECT cx.*, u.nome AS aberto_por_nome FROM caixa cx "
                   "LEFT JOIN usuario u ON u.id = cx.aberto_por WHERE cx.id = ?", (id_caixa,))
    movs = query("SELECT m.*, u.nome AS usuario_nome FROM caixa_mov m LEFT JOIN usuario u ON u.id = m.id_usuario "
                 "WHERE m.id_caixa = ? AND m.D_E_L_E_T = 0 ORDER BY m.id", (id_caixa,))
    gaveta = dinheiro(cx["saldo_inicial"])
    por_forma = {f: Decimal("0.00") for f in FORMAS_PAGAMENTO}
    entradas = saidas = Decimal("0.00")
    for m in movs:
        v = dinheiro(m["valor"])
        entra = m["tipo"] in ("SUPRIMENTO", "RECEBIMENTO")
        if m["tipo"] in ("RECEBIMENTO", "PAGAMENTO"):
            por_forma[m["forma_pagamento"]] += v if entra else -v
            entradas += v if entra else 0
            saidas += 0 if entra else v
        if m["forma_pagamento"] == "dinheiro":
            gaveta += v if entra else -v
    return {"caixa": dict(cx), "movs": [dict(m) for m in movs], "gaveta": gaveta,
            "por_forma": por_forma, "recebido": entradas, "pago": saidas}


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard (única tela com KPI)
# ──────────────────────────────────────────────────────────────────────────────

@financeiro_bp.route("/")
@login_required
def dashboard():
    _exige("financeiro", "ver")
    periodo, de, ate = periodo_do_request(request.args)
    hoje = hoje_local().isoformat()

    def soma(sql, params=()):
        row = query_one(sql, params)
        return dinheiro(row[0] if row and row[0] is not None else 0)

    filtro = " AND data_pagamento BETWEEN ? AND ?" if de else ""
    p = (de, ate) if de else ()
    recebido = soma("SELECT SUM(valor) FROM financeiro WHERE tipo='RECEBER' AND status='pago' AND D_E_L_E_T=0" + filtro, p)
    pago = soma("SELECT SUM(valor) FROM financeiro WHERE tipo='PAGAR' AND status='pago' AND D_E_L_E_T=0" + filtro, p)
    recebido_hoje = soma("SELECT SUM(valor) FROM financeiro WHERE tipo='RECEBER' AND status='pago' "
                         "AND D_E_L_E_T=0 AND data_pagamento = ?", (hoje,))
    os_row = query_one("SELECT COUNT(DISTINCT id_os) FROM financeiro WHERE tipo='RECEBER' AND status='pago' "
                       "AND D_E_L_E_T=0 AND id_os IS NOT NULL" + filtro, p)
    recebido_os = soma("SELECT SUM(valor) FROM financeiro WHERE tipo='RECEBER' AND status='pago' "
                       "AND D_E_L_E_T=0 AND id_os IS NOT NULL" + filtro, p)
    qtd_os = int(os_row[0] or 0)
    a_receber = soma("SELECT SUM(valor) FROM financeiro WHERE tipo='RECEBER' AND status='aberto' "
                     "AND D_E_L_E_T=0 AND data_vencimento >= ?", (hoje,))
    vencido = query_one("SELECT SUM(valor), COUNT(*) FROM financeiro WHERE tipo='RECEBER' AND status='aberto' "
                        "AND D_E_L_E_T=0 AND data_vencimento < ?", (hoje,))
    kpis = {
        "recebido": recebido, "recebido_hoje": recebido_hoje,
        "ticket": (recebido_os / qtd_os).quantize(Decimal("0.01")) if qtd_os else Decimal("0.00"),
        "qtd_os": qtd_os, "a_receber": a_receber,
        "vencido": dinheiro(vencido[0] or 0), "qtd_vencido": int(vencido[1] or 0),
        "saldo": recebido - pago, "pago": pago,
    }
    proximos = query(
        """SELECT f.*, c.razao_social AS cliente FROM financeiro f
             LEFT JOIN cliente c ON c.id = f.id_cliente
            WHERE f.status = 'aberto' AND f.D_E_L_E_T = 0 AND f.data_vencimento BETWEEN ? AND ?
            ORDER BY f.data_vencimento, f.id LIMIT 10""",
        (hoje, (hoje_local() + timedelta(days=7)).isoformat()),
    )
    return render_template("financeiro/dashboard.html", k=kpis, proximos=[dict(r) for r in proximos],
                           periodos=PERIODOS, periodo_sel=periodo, periodo_de=de, periodo_ate=ate,
                           caixa=caixa_aberto())


# ──────────────────────────────────────────────────────────────────────────────
# Contas a receber / a pagar (listagem operacional, sem KPI)
# ──────────────────────────────────────────────────────────────────────────────

def _lista(tipo: str):
    _exige(MODULO_TIPO[tipo], "ver")
    status = (request.args.get("status") or "aberto").strip()
    if status not in {s for s, _ in STATUS_LISTA}:
        status = "aberto"
    periodo, de, ate = periodo_do_request(request.args)
    hoje = hoje_local().isoformat()
    sql = """SELECT f.*, c.razao_social AS cliente FROM financeiro f
               LEFT JOIN cliente c ON c.id = f.id_cliente
              WHERE f.tipo = ? AND f.D_E_L_E_T = 0"""
    params: list = [tipo]
    if status == "vencido":
        sql += " AND f.status = 'aberto' AND f.data_vencimento < ?"
        params.append(hoje)
    elif status:
        sql += " AND f.status = ?"
        params.append(status)
    if de:
        sql += " AND f.data_vencimento BETWEEN ? AND ?"
        params += [de, ate]
    sql += " ORDER BY f.data_vencimento, f.id"
    titulos = []
    for r in query(sql, tuple(params)):
        t = dict(r)
        t["vencido"] = t["status"] == "aberto" and (t["data_vencimento"] or "") < hoje
        titulos.append(t)
    return render_template(
        "financeiro/titulos.html", tipo=tipo, titulos=titulos,
        pode_editar=current_user.pode(MODULO_TIPO[tipo], "editar"),
        status_sel=status, status_opcoes=[{"valor": s, "rotulo": r} for s, r in STATUS_LISTA],
        status_rotulo=dict(STATUS_LISTA).get(status, "Em aberto"),
        formas=[{"valor": k, "rotulo": v} for k, v in FORMAS_PAGAMENTO.items()],
        rotulo_forma=FORMAS_PAGAMENTO,
        periodos=PERIODOS, periodo_sel=periodo, periodo_de=de, periodo_ate=ate,
        hoje=hoje, caixa=caixa_aberto(),
    )


@financeiro_bp.route("/receber")
@login_required
def receber():
    return _lista("RECEBER")


@financeiro_bp.route("/pagar")
@login_required
def pagar():
    return _lista("PAGAR")


def _volta(tipo: str):
    return redirect(request.referrer or url_for(f"financeiro.{ROTA_TIPO[tipo]}"))


def _titulo_ou_404(id_titulo: int):
    tit = query_one("SELECT * FROM financeiro WHERE id = ? AND D_E_L_E_T = 0", (id_titulo,))
    if tit is None:
        abort(404)
    _exige(MODULO_TIPO[tit["tipo"]], "editar")
    return tit


@financeiro_bp.route("/titulo/novo", methods=["POST"])
@login_required
def titulo_novo():
    campos = ("tipo", "descricao", "valor", "data_vencimento", "parcelas", "id_cliente", "fornecedor", "observacoes")
    valores = {k: (request.form.get(k) or "").strip() for k in campos}
    tipo = valores["tipo"].upper()
    if tipo not in MODULO_TIPO:
        abort(400)
    _exige(MODULO_TIPO[tipo], "editar")
    try:
        dados = TituloIn(**valores)
    except ValidationError as exc:
        flash("Título não salvo: " + "; ".join(_erros(exc).values()), "erro")
        return _volta(tipo)
    if dados.id_cliente and not query_one("SELECT 1 FROM cliente WHERE id = ? AND D_E_L_E_T = 0",
                                          (int(dados.id_cliente),)):
        flash("Cliente não encontrado.", "erro")
        return _volta(tipo)
    with transaction() as db:
        ids = criar_titulos(db, dados, current_user.id)
    log_acesso("FIN_TITULO_CRIADO", current_user.id, f"tipo={tipo} ids={ids}")
    flash("Título lançado." if len(ids) == 1 else f"{len(ids)} parcelas lançadas.", "sucesso")
    return _volta(tipo)


@financeiro_bp.route("/titulo/<int:id_titulo>/baixar", methods=["POST"])
@login_required
def titulo_baixar(id_titulo: int):
    tit = _titulo_ou_404(id_titulo)
    try:
        baixa = BaixaIn(forma_pagamento=(request.form.get("forma_pagamento") or "").strip(),
                        data_pagamento=(request.form.get("data_pagamento") or hoje_local().isoformat()).strip())
    except ValidationError as exc:
        flash("Baixa não feita: " + "; ".join(_erros(exc).values()), "erro")
        return _volta(tit["tipo"])
    with transaction() as db:
        erro = baixar_titulo(db, id_titulo, baixa, current_user.id)
    if erro:
        flash(erro, "erro")
    else:
        log_acesso("FIN_BAIXA", current_user.id, f"titulo={id_titulo} forma={baixa.forma_pagamento}")
        flash("Baixa registrada.", "sucesso")
    return _volta(tit["tipo"])


@financeiro_bp.route("/titulo/<int:id_titulo>/parcelar", methods=["POST"])
@login_required
def titulo_parcelar(id_titulo: int):
    tit = _titulo_ou_404(id_titulo)
    n = request.form.get("parcelas", type=int) or 0
    with transaction() as db:
        erro = parcelar_titulo(db, id_titulo, n)
    flash(erro or f"Título parcelado em {n}x.", "erro" if erro else "sucesso")
    if not erro:
        log_acesso("FIN_PARCELADO", current_user.id, f"titulo={id_titulo} n={n}")
    return _volta(tit["tipo"])


@financeiro_bp.route("/titulo/<int:id_titulo>/cancelar", methods=["POST"])
@login_required
def titulo_cancelar(id_titulo: int):
    tit = _titulo_ou_404(id_titulo)
    with transaction() as db:
        cur = db.execute(
            "UPDATE financeiro SET status = 'cancelado' WHERE id = ? AND status = 'aberto' AND D_E_L_E_T = 0",
            (id_titulo,),
        )
    if cur.rowcount == 1:
        log_acesso("FIN_CANCELADO", current_user.id, f"titulo={id_titulo}")
        flash("Título cancelado.", "sucesso")
    else:
        flash("Só título em aberto pode ser cancelado.", "erro")
    return _volta(tit["tipo"])


@financeiro_bp.route("/recibo/<int:id_titulo>")
@login_required
def recibo(id_titulo: int):
    _exige("contas_receber", "ver")
    tit = query_one(
        """SELECT f.*, c.razao_social AS cliente, c.cpf_cnpj FROM financeiro f
             LEFT JOIN cliente c ON c.id = f.id_cliente
            WHERE f.id = ? AND f.tipo = 'RECEBER' AND f.status = 'pago' AND f.D_E_L_E_T = 0""",
        (id_titulo,),
    )
    if tit is None:
        abort(404)
    empresa = query_one("SELECT valor FROM configuracao WHERE chave = 'empresa_nome'")
    return render_template("financeiro/recibo.html", t=dict(tit), rotulo_forma=FORMAS_PAGAMENTO,
                           empresa=empresa["valor"] if empresa else "OficinaApp",
                           emitido=agora_local().strftime("%d/%m/%Y %H:%M"))


# ──────────────────────────────────────────────────────────────────────────────
# Caixa (PDV)
# ──────────────────────────────────────────────────────────────────────────────

@financeiro_bp.route("/caixa")
@login_required
def caixa():
    _exige("caixa", "ver")
    cx = caixa_aberto()
    historico = query(
        """SELECT cx.*, ua.nome AS aberto_por_nome, uf.nome AS fechado_por_nome FROM caixa cx
             LEFT JOIN usuario ua ON ua.id = cx.aberto_por
             LEFT JOIN usuario uf ON uf.id = cx.fechado_por
            WHERE cx.status = 'fechado' AND cx.D_E_L_E_T = 0 ORDER BY cx.id DESC LIMIT 30"""
    )
    return render_template("financeiro/caixa.html", resumo=resumo_caixa(cx["id"]) if cx else None,
                           historico=[dict(h) for h in historico], rotulo_forma=FORMAS_PAGAMENTO,
                           pode_editar=current_user.pode("caixa", "editar"))


def _valor_caixa():
    try:
        return CaixaValorIn(valor=(request.form.get("valor") or "").strip(),
                            descricao=(request.form.get("descricao") or "").strip() or None), None
    except ValidationError as exc:
        return None, "; ".join(_erros(exc).values())


@financeiro_bp.route("/caixa/abrir", methods=["POST"])
@login_required
def caixa_abrir():
    _exige("caixa", "editar")
    dados, erro = _valor_caixa()
    if erro:
        flash(erro, "erro")
        return redirect(url_for("financeiro.caixa"))
    try:
        with transaction() as db:
            db.execute("INSERT INTO caixa (aberto_em, aberto_por, saldo_inicial, status) VALUES (?, ?, ?, 'aberto')",
                       (agora_utc_texto(), current_user.id, float(dinheiro(dados.valor))))
    except sqlite3.IntegrityError:   # índice único: já há caixa aberto
        flash("Já existe um caixa aberto.", "erro")
        return redirect(url_for("financeiro.caixa"))
    log_acesso("CAIXA_ABERTO", current_user.id, f"inicial={dados.valor}")
    flash("Caixa aberto.", "sucesso")
    return redirect(url_for("financeiro.caixa"))


@financeiro_bp.route("/caixa/movimento", methods=["POST"])
@login_required
def caixa_movimento():
    _exige("caixa", "editar")
    tipo = (request.form.get("tipo") or "").strip().upper()
    if tipo not in ("SUPRIMENTO", "SANGRIA"):
        abort(400)
    dados, erro = _valor_caixa()
    if not erro and dinheiro(dados.valor) <= 0:
        erro = "O valor tem que ser maior que zero."
    if not erro and not dados.descricao:
        erro = "Diga o motivo (ex.: troco do dia, depósito no banco)."
    if erro:
        flash(erro, "erro")
        return redirect(url_for("financeiro.caixa"))
    with transaction() as db:
        cx = caixa_aberto(db)
        if cx is None:
            flash("Abra o caixa antes.", "erro")
            return redirect(url_for("financeiro.caixa"))
        if tipo == "SANGRIA":
            gaveta = resumo_caixa(cx["id"])["gaveta"]
            if dinheiro(dados.valor) > gaveta:
                flash(f"Sangria maior que o dinheiro na gaveta ({moeda(gaveta)}).", "erro")
                return redirect(url_for("financeiro.caixa"))
        db.execute(
            """INSERT INTO caixa_mov (id_caixa, tipo, forma_pagamento, valor, descricao, id_usuario, quando)
               VALUES (?, ?, 'dinheiro', ?, ?, ?, ?)""",
            (cx["id"], tipo, float(dinheiro(dados.valor)), dados.descricao, current_user.id, agora_utc_texto()),
        )
    log_acesso("CAIXA_" + tipo, current_user.id, f"valor={dados.valor}")
    flash("Suprimento registrado." if tipo == "SUPRIMENTO" else "Sangria registrada.", "sucesso")
    return redirect(url_for("financeiro.caixa"))


@financeiro_bp.route("/caixa/fechar", methods=["POST"])
@login_required
def caixa_fechar():
    _exige("caixa", "editar")
    dados, erro = _valor_caixa()
    if erro:
        flash("Informe quanto tem na gaveta: " + erro, "erro")
        return redirect(url_for("financeiro.caixa"))
    cx = caixa_aberto()
    if cx is None:
        flash("Não há caixa aberto.", "erro")
        return redirect(url_for("financeiro.caixa"))
    calculado = resumo_caixa(cx["id"])["gaveta"]
    contado = dinheiro(dados.valor)
    with transaction() as db:
        cur = db.execute(
            """UPDATE caixa SET status = 'fechado', fechado_em = ?, fechado_por = ?,
                      saldo_calculado = ?, saldo_informado = ?, diferenca = ?, observacoes = ?
                WHERE id = ? AND status = 'aberto'""",
            (agora_utc_texto(), current_user.id, float(calculado), float(contado),
             float(contado - calculado), dados.descricao, cx["id"]),
        )
    if cur.rowcount != 1:
        flash("O caixa já foi fechado.", "erro")
        return redirect(url_for("financeiro.caixa"))
    log_acesso("CAIXA_FECHADO", current_user.id, f"caixa={cx['id']} diferenca={contado - calculado}")
    dif = contado - calculado
    msg = "Caixa fechado e conferido." if dif == 0 else (
        f"Caixa fechado com diferença de {moeda(dif)} (contado {moeda(contado)}, sistema {moeda(calculado)}).")
    flash(msg, "sucesso" if dif == 0 else "erro")
    return redirect(url_for("financeiro.caixa"))
