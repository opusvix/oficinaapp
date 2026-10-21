"""Estoque de Peças (Fase 5).

Regras desta fase:
- VER abre a listagem e o detalhe; EDITAR abre cadastro, edição e exclusão.
- Alerta visual (badge vermelho) quando estoque_atual <= estoque_minimo.
- Entrada/saída manual gera movimento_estoque e ajusta estoque_atual da peça.
- Validação server-side em Pydantic (modules/validacao_peca.py).
- Exclusão é soft delete (D_E_L_E_T=1 + deleted_at).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import json

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from core.db import query, query_one, transaction
from modules.validacao_peca import UNIDADES, PecaIn

estoque_bp = Blueprint("estoque", __name__, url_prefix="/estoque")


@estoque_bp.context_processor
def _opcoes_unidade():
    return {"unidades_opcoes": [{"valor": u, "rotulo": u} for u in UNIDADES]}

CAMPOS_FORM = (
    "codigo", "descricao", "unidade", "preco_custo", "preco_venda",
    "estoque_atual", "estoque_minimo", "localizacao",
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_decimal(valor, casas=2):
    """Formata decimal brasileiro: '10.5' -> '10,50'."""
    try:
        v = float(str(valor).replace(",", ".") or 0)
    except (ValueError, TypeError):
        v = 0
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _enriquecer(row) -> dict:
    """Linha do banco -> dict pronto pro template (com flag de estoque baixo)."""
    p = dict(row)
    estoque_atual = float(str(p.get("estoque_atual") or 0).replace(",", "."))
    estoque_minimo = float(str(p.get("estoque_minimo") or 0).replace(",", "."))
    p["estoque_baixo"] = estoque_atual <= estoque_minimo and estoque_minimo > 0
    p["estoque_atual_fmt"] = _fmt_decimal(p.get("estoque_atual"), 3)
    p["preco_custo_fmt"] = _fmt_decimal(p.get("preco_custo"), 2)
    p["preco_venda_fmt"] = _fmt_decimal(p.get("preco_venda"), 2)
    return p


def _listagem() -> list[dict]:
    linhas = query(
        """SELECT id, codigo, descricao, unidade, preco_custo, preco_venda,
                  estoque_atual, estoque_minimo, localizacao
             FROM peca
            WHERE D_E_L_E_T = 0
            ORDER BY codigo COLLATE NOCASE"""
    )
    return [_enriquecer(r) for r in linhas]


def _pode_editar() -> bool:
    return bool(current_user.pode("pecas", "editar"))


def _nao_pode_ver():
    if not current_user.pode("pecas", "ver"):
        abort(403)


def _valores_form() -> dict:
    return {k: (request.form.get(k) or "").strip() for k in CAMPOS_FORM}


# ──────────────────────────────────────────────────────────────────────────────
# API de busca (SelectBusca do modal de item da OS)
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/api/pecas")
@login_required
def api_pecas():
    """Busca de peças pro SelectBusca do modal de item da OS.

    Acesso: quem pode VER os (técnico monta orçamento) ou VER peças.
    Resposta no formato literal do selectbusca.js: {"itens": [{valor, rotulo, sub}]}.
    """
    if not (current_user.pode("os", "ver") or current_user.pode("pecas", "ver")):
        abort(403)

    termo = (request.args.get("q") or "").strip()
    sql = ("SELECT id, codigo, descricao, preco_venda, estoque_atual "
           "  FROM peca "
           " WHERE D_E_L_E_T = 0")
    params: list = []
    if termo:
        sql += (" AND (codigo LIKE ? COLLATE NOCASE"
                "      OR descricao LIKE ? COLLATE NOCASE)")
        params.extend([f"%{termo}%", f"%{termo}%"])
    sql += " ORDER BY descricao COLLATE NOCASE LIMIT 12"

    itens = []
    for r in query(sql, tuple(params)):
        preco_venda = _fmt_decimal(r["preco_venda"], 2)
        rotulo = r["descricao"]
        if r["codigo"]:
            rotulo = f"{r['codigo']} — {r['descricao']}"
        itens.append({
            "valor": r["id"],
            "rotulo": rotulo,
            "sub": (f"R$ {preco_venda} · estoque "
                    f"{_fmt_decimal(r['estoque_atual'], 3)}"),
            # extras que o JS do modal usa pra preencher descrição/preço
            "descricao": r["descricao"],
            "preco": preco_venda,
        })
    return jsonify({"itens": itens})


# ──────────────────────────────────────────────────────────────────────────────
# Listagem (TabelaAvancada)
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/")
@login_required
def listar():
    _nao_pode_ver()
    so_baixo = request.args.get("baixo") == "1"   # atalho do Início: "abaixo do mínimo"
    pecas = _listagem()
    if so_baixo:
        pecas = [p for p in pecas if p["estoque_baixo"]]
    return render_template(
        "estoque/lista.html",
        pecas=pecas,
        so_baixo=so_baixo,
        pode_editar=_pode_editar(),
        erros={},
        valores={},
        modal_aberto=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cadastro / edição
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/salvar", methods=["POST"])
@login_required
def salvar():
    if not _pode_editar():
        abort(403)

    valores = _valores_form()
    id_peca = request.form.get("id", type=int)
    erros: dict[str, str] = {}

    dados: PecaIn | None = None
    try:
        dados = PecaIn(**valores)
    except Exception as exc:  # pydantic.ValidationError
        mensagens = exc.errors() if hasattr(exc, "errors") else [{"msg": str(exc)}]
        for item in mensagens:
            campo = (item.get("loc") or ["formulario"])[0] if isinstance(item, dict) else "formulario"
            erros[str(campo)] = item.get("msg", str(item))

    if erros:
        return render_template(
            "estoque/lista.html",
            pecas=_listagem(),
            pode_editar=True,
            erros=erros,
            valores=valores,
            modal_aberto=True,
        ), 422

    linhas = dados.para_linhas()

    try:
        with transaction() as db:
            if id_peca:
                atual = query_one(
                    "SELECT id FROM peca WHERE id = ? AND D_E_L_E_T = 0",
                    (id_peca,),
                )
                if atual is None:
                    abort(404)
                cols = ", ".join(f"{k} = ?" for k in linhas)
                db.execute(
                    f"UPDATE peca SET {cols} WHERE id = ?",
                    (*linhas.values(), id_peca),
                )
            else:
                cols = ", ".join(linhas)
                marcadores = ", ".join("?" for _ in linhas)
                db.execute(
                    f"INSERT INTO peca ({cols}) VALUES ({marcadores})",
                    tuple(linhas.values()),
                )
    except sqlite3.IntegrityError:
        flash("Não foi possível salvar: já existe peça com este código.", "erro")
        return redirect(url_for("estoque.listar"))

    flash("Peça salva.", "sucesso")
    return redirect(url_for("estoque.listar"))


# ──────────────────────────────────────────────────────────────────────────────
# Exclusão (soft delete)
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/<int:id_peca>/excluir", methods=["POST"])
@login_required
def excluir(id_peca: int):
    if not _pode_editar():
        abort(403)
    peca_row = query_one(
        "SELECT id, codigo FROM peca WHERE id = ? AND D_E_L_E_T = 0",
        (id_peca,),
    )
    if peca_row is None:
        abort(404)
    with transaction() as db:
        db.execute(
            "UPDATE peca SET D_E_L_E_T = 1, deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (id_peca,),
        )
    flash(f'Peça "{peca_row["codigo"]}" excluída (soft delete).', "sucesso")
    return redirect(url_for("estoque.listar"))


# ──────────────────────────────────────────────────────────────────────────────
# Entrada / saída manual de estoque
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/<int:id_peca>/movimento", methods=["POST"])
@login_required
def movimento(id_peca: int):
    if not _pode_editar():
        abort(403)
    peca_row = query_one(
        "SELECT id, codigo, estoque_atual FROM peca WHERE id = ? AND D_E_L_E_T = 0",
        (id_peca,),
    )
    if peca_row is None:
        abort(404)

    tipo = (request.form.get("tipo") or "").upper()
    quantidade_raw = (request.form.get("quantidade") or "").strip().replace(",", ".")
    observacoes = (request.form.get("observacoes") or "").strip()

    if tipo not in ("ENTRADA", "SAIDA"):
        flash("Tipo de movimento inválido.", "erro")
        return redirect(url_for("estoque.listar"))

    try:
        quantidade = float(quantidade_raw)
    except ValueError:
        flash("Quantidade inválida.", "erro")
        return redirect(url_for("estoque.listar"))
    if quantidade <= 0:
        flash("Quantidade deve ser maior que zero.", "erro")
        return redirect(url_for("estoque.listar"))

    estoque_atual = float(peca_row["estoque_atual"] or 0)
    if tipo == "SAIDA" and quantidade > estoque_atual:
        flash("Estoque insuficiente para saída.", "erro")
        return redirect(url_for("estoque.listar"))

    novo_estoque = estoque_atual + quantidade if tipo == "ENTRADA" else estoque_atual - quantidade

    try:
        with transaction() as db:
            db.execute(
                "UPDATE peca SET estoque_atual = ? WHERE id = ?",
                (novo_estoque, id_peca),
            )
            db.execute(
                """INSERT INTO movimento_estoque
                       (id_peca, tipo, quantidade, origem_tipo, observacoes)
                   VALUES (?, ?, ?, 'AJUSTE', ?)""",
                (id_peca, tipo, quantidade, observacoes or None),
            )
    except sqlite3.Error:
        flash("Erro ao registrar movimento de estoque.", "erro")
        return redirect(url_for("estoque.listar"))

    flash(f"Movimento de {tipo} registrado. Novo estoque: {novo_estoque:,.3f}".replace(",", "X").replace(".", ",").replace("X", "."), "sucesso")
    return redirect(url_for("estoque.listar"))


# ──────────────────────────────────────────────────────────────────────────────
# Detalhe da peça (histórico de movimentos)
# ──────────────────────────────────────────────────────────────────────────────

@estoque_bp.route("/<int:id_peca>")
@login_required
def detalhe(id_peca: int):
    _nao_pode_ver()
    peca_row = query_one(
        "SELECT * FROM peca WHERE id = ? AND D_E_L_E_T = 0",
        (id_peca,),
    )
    if peca_row is None:
        abort(404)
    movimentos = query(
        """SELECT id, tipo, quantidade, observacoes, datestamp
             FROM movimento_estoque
            WHERE id_peca = ? AND D_E_L_E_T = 0
            ORDER BY datestamp DESC, id DESC""",
        (id_peca,),
    )
    return render_template(
        "estoque/detalhe.html",
        peca=_enriquecer(peca_row),
        movimentos=[dict(m) for m in movimentos],
        pode_editar=_pode_editar(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Importação por planilha (Padrao_Excel_Template_Importacao)
# ──────────────────────────────────────────────────────────────────────────────

from modules.importacao_estoque import gerar_modelo, ler_linhas, validar  # noqa: E402

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@estoque_bp.route("/modelo.xlsx")
@login_required
def modelo_xlsx():
    if not _pode_editar():
        abort(403)
    r = Response(gerar_modelo(), mimetype=_XLSX_MIME)
    r.headers["Content-Disposition"] = 'attachment; filename="modelo_estoque_pecas.xlsx"'
    return r


@estoque_bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    if not _pode_editar():
        abort(403)
    if request.method == "GET":
        return render_template("estoque/importar.html", etapa="upload")

    arquivo = request.files.get("planilha")
    if not arquivo or not arquivo.filename:
        flash("Escolha a planilha preenchida (.xlsx).", "erro")
        return render_template("estoque/importar.html", etapa="upload")
    if not arquivo.filename.lower().endswith(".xlsx"):
        flash("O arquivo precisa ser um Excel .xlsx (o modelo que você baixou).", "erro")
        return render_template("estoque/importar.html", etapa="upload")
    try:
        linhas = ler_linhas(arquivo.stream)
    except ValueError as exc:
        flash(str(exc), "erro")
        return render_template("estoque/importar.html", etapa="upload")
    if not linhas:
        flash("A planilha não tem nenhuma linha preenchida.", "erro")
        return render_template("estoque/importar.html", etapa="upload")

    resultado = validar(linhas)
    # carrega as linhas CRUAS pra confirmação: confirmar revalida idêntico (uma fonte só)
    return render_template("estoque/importar.html", etapa="previa",
                           resumo=resultado["resumo"], validas=resultado["validas"],
                           problemas=resultado["problemas"], dados=json.dumps(linhas, default=str))


@estoque_bp.route("/importar/confirmar", methods=["POST"])
@login_required
def importar_confirmar():
    if not _pode_editar():
        abort(403)
    try:
        linhas = json.loads(request.form.get("dados") or "[]")
        assert isinstance(linhas, list)
    except (ValueError, AssertionError):
        flash("Sessão da importação expirou. Suba a planilha de novo.", "erro")
        return redirect(url_for("estoque.importar"))

    resultado = validar(linhas)   # revalida as mesmas linhas cruas (nada vem do cliente sem passar aqui)
    validas = resultado["validas"]
    if not validas:
        flash("Nenhuma linha válida para importar.", "erro")
        return render_template("estoque/importar.html", etapa="previa",
                               resumo=resultado["resumo"], validas=validas,
                               problemas=resultado["problemas"], dados=request.form.get("dados"))
    criadas = atualizadas = 0
    with transaction() as db:
        for v in validas:
            campos = v["linhas"]
            existe = db.execute("SELECT id FROM peca WHERE codigo = ? AND D_E_L_E_T = 0",
                                (campos["codigo"],)).fetchone()
            if existe:
                cols = ", ".join(f"{k} = ?" for k in campos if k != "codigo")
                db.execute(f"UPDATE peca SET {cols} WHERE id = ?",
                           (*[campos[k] for k in campos if k != "codigo"], existe["id"]))
                atualizadas += 1
            else:
                cols = ", ".join(campos)
                db.execute(f"INSERT INTO peca ({cols}) VALUES ({', '.join('?' for _ in campos)})",
                           tuple(campos.values()))
                criadas += 1
    from core.auditoria import log_acesso
    log_acesso("ESTOQUE_IMPORTADO", current_user.id, f"novas={criadas} atualizadas={atualizadas}")
    flash(f"Importação concluída: {criadas} peça(s) nova(s), {atualizadas} atualizada(s).", "sucesso")
    return redirect(url_for("estoque.listar"))
