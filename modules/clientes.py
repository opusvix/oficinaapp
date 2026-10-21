"""Clientes + equipamentos do cliente (Fase 4).

Regras desta fase:
- VER abre listagem e detalhe; EDITAR abre cadastro, edição e exclusão.
- Exclusão é soft delete (D_E_L_E_T=1 + deleted_at): o histórico de OS do
  equipamento não pode sumir porque o dono saiu da base.
- Validação server-side em Pydantic (modules/validacao_clientes.py); o form
  HTML só adianta o feedback, não é a trava.
- Tag/Patrimônio em branco no equipamento: o backend gera ESG{id} (mesma
  regra que a OS vai usar).
- Foto opcional: extensão e 5 MB checados no servidor, nome aleatório —
  nome do arquivo do usuário nunca chega ao disco.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from flask import (
    Blueprint,
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
from pydantic import ValidationError

from core.db import query, query_one, transaction
from core.upload import salvar_imagem
from modules.validacao_clientes import UFFS, ClienteIn, digitos

clientes_bp = Blueprint("clientes", __name__, url_prefix="/clientes")


@clientes_bp.context_processor
def _opcoes_uf():
    return {"uf_lista": [{"valor": u, "rotulo": u} for u in sorted(UFFS)]}


CAMPOS_FORM = (
    "razao_social", "nome_fantasia", "cpf_cnpj", "ie_rg", "email",
    "telefone1", "telefone2", "cep", "logradouro", "numero", "complemento",
    "bairro", "cidade", "uf", "observacoes",
)


# ──────────────────────────────────────────────────────────────────────────────
# Formatação de exibição (banco guarda dígito limpo)
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_doc(valor: str | None) -> str:
    d = digitos(valor)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return valor or "—"


def _fmt_tel(valor: str | None) -> str:
    d = digitos(valor)
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return valor or "—"


def _fmt_cep(valor: str | None) -> str:
    d = digitos(valor)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (valor or "—")


def _enriquecer(row) -> dict:
    """Linha do banco -> dict pronto pro template (com máscaras de leitura)."""
    c = dict(row)
    c["doc_fmt"] = _fmt_doc(c.get("cpf_cnpj")) if c.get("cpf_cnpj") else "—"
    c["tel_fmt"] = _fmt_tel(c.get("telefone1")) if c.get("telefone1") else "—"
    c["cep_fmt"] = _fmt_cep(c.get("cep")) if c.get("cep") else None
    c["cidade_uf"] = " — ".join(x for x in (c.get("cidade"), c.get("uf")) if x) or "—"
    return c


def _listagem() -> list[dict]:
    linhas = query(
        """SELECT c.id, c.razao_social, c.nome_fantasia, c.cpf_cnpj, c.email,
                  c.telefone1, c.cidade, c.uf, c.foto, c.observacoes,
                  (SELECT COUNT(*) FROM equipamento e
                    WHERE e.id_cliente = c.id AND e.D_E_L_E_T = 0) AS qtd_equipamentos
             FROM cliente c
            WHERE c.D_E_L_E_T = 0
            ORDER BY c.razao_social COLLATE NOCASE"""
    )
    return [_enriquecer(r) for r in linhas]


def _pode_editar() -> bool:
    return bool(current_user.pode("clientes", "editar"))


def _nao_pode_ver():
    if not current_user.pode("clientes", "ver"):
        abort(403)


# ──────────────────────────────────────────────────────────────────────────────
# Listagem (TabelaAvancada)
# ──────────────────────────────────────────────────────────────────────────────

@clientes_bp.route("/")
@login_required
def listar():
    _nao_pode_ver()
    # ?editar=<id> vem do detalhe: abre o modal já preenchido
    editar_id = request.args.get("editar", type=int)
    return render_template(
        "clientes/lista.html",
        clientes=_listagem(),
        pode_editar=_pode_editar(),
        uffs=sorted(UFFS),
        erros={},
        valores={},
        modal_aberto=False,
        editar_id=editar_id if editar_id else None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cadastro / edição
# ──────────────────────────────────────────────────────────────────────────────

def _valores_form() -> dict:
    return {k: (request.form.get(k) or "").strip() for k in CAMPOS_FORM}


def _processar_foto(erros: dict) -> str | None:
    """Salva a foto em static/uploads/clientes/. Devolve o caminho relativo
    (ou None). Erro de arquivo vira erro de campo, não exception 500."""
    arq = request.files.get("foto")
    if not arq or not arq.filename:
        return None
    relativo, erro = salvar_imagem(arq, "clientes")
    if erro:
        erros["foto"] = erro
    return relativo


def _apaga_foto(relativo: str | None) -> None:
    """Apaga a foto antiga (best effort: foto sumida não derruba o save)."""
    if not relativo or not relativo.startswith("uploads/"):
        return
    try:
        (Path(current_app.root_path) / "static" / relativo).unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning("FOTO_NAO_APAGADA %s", relativo)


@clientes_bp.route("/salvar", methods=["POST"])
@login_required
def salvar():
    if not _pode_editar():
        abort(403)

    valores = _valores_form()
    id_cliente = request.form.get("id", type=int)
    valores["id"] = request.form.get("id") or ""  # volta no form se erro
    erros: dict[str, str] = {}

    dados: ClienteIn | None = None
    try:
        # "id" só volta pro form em caso de erro: fora do modelo, senão o extra="forbid"
        # recusa TODO salvamento (bug de 19/10 a 20/10, achado pelo teste_fluxo_completo)
        dados = ClienteIn(**{k: v for k, v in valores.items() if k != "id"})
    except ValidationError as exc:
        for item in exc.errors():
            campo = item["loc"][0] if item["loc"] else "formulario"
            erros[str(campo)] = item["msg"]

    foto = _processar_foto(erros)

    if erros:
        # Volta pro form com os erros campo a campo e o que já foi digitado —
        # flash genérico aqui seria amadorismo (Padrao_Validacao_de_Input).
        return render_template(
            "clientes/lista.html",
            clientes=_listagem(),
            pode_editar=True,
            uffs=sorted(UFFS),
            erros=erros,
            valores=valores,
            modal_aberto=True,
            editar_id=None,
        ), 422

    linhas = dados.para_linhas()

    try:
        with transaction() as db:
            if id_cliente:
                atual = query_one(
                    "SELECT id, foto FROM cliente WHERE id = ? AND D_E_L_E_T = 0",
                    (id_cliente,),
                )
                if atual is None:
                    abort(404)
                if foto and atual["foto"]:
                    _apaga_foto(atual["foto"])
                if foto:
                    linhas["foto"] = foto
                cols = ", ".join(f"{k} = ?" for k in linhas)
                db.execute(
                    f"UPDATE cliente SET {cols} WHERE id = ?",
                    (*linhas.values(), id_cliente),
                )
            else:
                if foto:
                    linhas["foto"] = foto
                cols = ", ".join(linhas)
                marcadores = ", ".join("?" for _ in linhas)
                db.execute(
                    f"INSERT INTO cliente ({cols}) VALUES ({marcadores})",
                    tuple(linhas.values()),
                )
    except sqlite3.IntegrityError:
        flash("Não foi possível salvar: já existe cliente com este CPF/CNPJ.",
              "erro")
        return redirect(url_for("clientes.listar"))

    flash("Cliente salvo.", "sucesso")
    return redirect(url_for("clientes.listar"))


# ──────────────────────────────────────────────────────────────────────────────
# Exclusão (soft delete)
# ──────────────────────────────────────────────────────────────────────────────

@clientes_bp.route("/<int:id_cliente>/excluir", methods=["POST"])
@login_required
def excluir(id_cliente: int):
    if not _pode_editar():
        abort(403)
    cliente = query_one(
        "SELECT id, razao_social, foto FROM cliente WHERE id = ? AND D_E_L_E_T = 0",
        (id_cliente,),
    )
    if cliente is None:
        abort(404)
    with transaction() as db:
        db.execute(
            "UPDATE cliente SET D_E_L_E_T = 1, deleted_at = CURRENT_TIMESTAMP "
            " WHERE id = ?",
            (id_cliente,),
        )
    _apaga_foto(cliente["foto"])
    flash(f"Cliente “{cliente['razao_social']}” excluído. "
          "O histórico fica no banco (soft delete).", "sucesso")
    return redirect(url_for("clientes.listar"))


# ──────────────────────────────────────────────────────────────────────────────
# Detalhe + histórico de equipamentos
# ──────────────────────────────────────────────────────────────────────────────

@clientes_bp.route("/<int:id_cliente>")
@login_required
def detalhe(id_cliente: int):
    _nao_pode_ver()
    cliente = query_one(
        "SELECT * FROM cliente WHERE id = ? AND D_E_L_E_T = 0", (id_cliente,)
    )
    if cliente is None:
        abort(404)
    equipamentos = query(
        """SELECT id, patrimonio, modelo, marca, numero_serie, descricao
             FROM equipamento
            WHERE id_cliente = ? AND D_E_L_E_T = 0
            ORDER BY patrimonio COLLATE NOCASE""",
        (id_cliente,),
    )
    return render_template(
        "clientes/detalhe.html",
        cliente=_enriquecer(cliente),
        equipamentos=[dict(e) for e in equipamentos],
        pode_editar=_pode_editar(),
        erros={},
        valores={},
        modal_aberto=False,
    )


@clientes_bp.route("/<int:id_cliente>/equipamentos", methods=["POST"])
@login_required
def novo_equipamento(id_cliente: int):
    if not _pode_editar():
        abort(403)
    cliente = query_one(
        "SELECT id, razao_social FROM cliente WHERE id = ? AND D_E_L_E_T = 0",
        (id_cliente,),
    )
    if cliente is None:
        abort(404)

    valores = {k: (request.form.get(k) or "").strip()
               for k in ("patrimonio", "modelo", "marca", "numero_serie", "descricao")}
    erros: dict[str, str] = {}
    limites = {"patrimonio": 50, "modelo": 150, "marca": 100, "numero_serie": 100}
    for campo, limite in limites.items():
        if len(valores[campo]) > limite:
            erros[campo] = f"Máximo de {limite} caracteres."
    if not any(valores.values()):
        erros["patrimonio"] = "Informe ao menos a patrinha/Tag ou o modelo."

    if erros:
        primeiro = next(iter(erros.values()))
        flash(f"Equipamento não salvo: {primeiro}", "erro")
        return redirect(url_for("clientes.detalhe", id_cliente=id_cliente))

    try:
        with transaction() as db:
            # Placeholder temporário: NOT NULL do patrimônio não deixa o
            # INSERT ir vazio, e o marcador único evita colidir o índice
            # único parcial enquanto a Tag não existe.
            marcador = f"__gerando_{uuid.uuid4().hex[:8]}__"
            cur = db.execute(
                """INSERT INTO equipamento
                       (id_cliente, patrimonio, modelo, marca, numero_serie, descricao)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (id_cliente, valores["patrimonio"] or marcador,
                 valores["modelo"] or None, valores["marca"] or None,
                 valores["numero_serie"] or None, valores["descricao"] or None),
            )
            if not valores["patrimonio"]:
                # Tag vazia -> backend gera ESG{id} (Padrao_Tag)
                db.execute(
                    "UPDATE equipamento SET patrimonio = ? WHERE id = ?",
                    (f"ESG{cur.lastrowid}", cur.lastrowid),
                )
    except sqlite3.IntegrityError:
        flash("Já existe equipamento com esta patrinha/Tag para este cliente.",
              "erro")
        return redirect(url_for("clientes.detalhe", id_cliente=id_cliente))

    flash("Equipamento cadastrado.", "sucesso")
    return redirect(url_for("clientes.detalhe", id_cliente=id_cliente))


# ──────────────────────────────────────────────────────────────────────────────
# SelectBusca: cidades já cadastradas (o campo aceita texto livre também)
# ──────────────────────────────────────────────────────────────────────────────

@clientes_bp.route("/api/busca")
@login_required
def api_busca():
    """SelectBusca de cliente (abertura de OS). Quem abre OS precisa achar o
    cliente mesmo sem ser dono do cadastro: vale VER clientes OU EDITAR OS."""
    if not (current_user.pode("clientes", "ver") or current_user.pode("os", "editar")):
        abort(403)
    termo = (request.args.get("q") or "").strip()
    sql = ("SELECT id, razao_social, nome_fantasia, cidade, uf FROM cliente "
           " WHERE D_E_L_E_T = 0")
    params: list = []
    if termo:
        sql += (" AND (razao_social LIKE ? COLLATE NOCASE OR nome_fantasia LIKE ? COLLATE NOCASE"
                "      OR cpf_cnpj LIKE ?)")
        params += [f"%{termo}%", f"%{termo}%", f"%{digitos(termo) or termo}%"]
    sql += " ORDER BY razao_social COLLATE NOCASE LIMIT 12"
    itens = [{
        "valor": r["id"],
        "rotulo": r["razao_social"],
        "sub": " · ".join(x for x in (r["nome_fantasia"], " / ".join(y for y in (r["cidade"], r["uf"]) if y)) if x),
    } for r in query(sql, tuple(params))]
    return jsonify({"itens": itens})


@clientes_bp.route("/api/cidades")
@login_required
def api_cidades():
    _nao_pode_ver()
    termo = (request.args.get("q") or "").strip()
    sql = ("SELECT DISTINCT cidade, uf FROM cliente "
           " WHERE D_E_L_E_T = 0 AND cidade IS NOT NULL AND cidade <> ''")
    params: list = []
    if termo:
        sql += " AND cidade LIKE ? COLLATE NOCASE"
        params.append(f"%{termo}%")
    sql += " ORDER BY cidade COLLATE NOCASE LIMIT 12"
    itens = [{"valor": r["cidade"], "rotulo": r["cidade"], "sub": r["uf"] or ""}
             for r in query(sql, tuple(params))]
    return jsonify({"itens": itens})
