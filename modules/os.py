"""Ordens de Serviço (Fase 6 - core).

Regras desta fase:
- VER abre a listagem; EDITAR abre abertura/edição.
- Técnico vê apenas suas OS (filtro por id_tecnico no backend).
- Patrimônio obrigatório: se vazio, backend gera ESG{idOS}.
- orcamento_status: pendente -> aprovado/recusado via link público do cliente.
- Exclusão é soft delete (D_E_L_E_T=1 + deleted_at).
"""
from __future__ import annotations

import base64
import binascii
import secrets
import sqlite3
from datetime import date, datetime, timedelta
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

from core.auditoria import log_acesso
from core.db import query, query_one, transaction
from core.tempo import agora_local, agora_utc, agora_utc_texto, hoje_local, ler_utc, limites_utc
from core.upload import salvar_imagem, tipo_real_imagem
from modules.validacao_os import ItemOSIn, OSIn

os_bp = Blueprint("os", __name__, url_prefix="/os")

_STATUS_VALIDOS = {"aberta", "avaliacao", "aprovada", "em_andamento", "entregue", "recusada"}
ORDEM_STATUS = ["aberta", "avaliacao", "aprovada", "em_andamento", "entregue", "recusada"]
ROTULOS_STATUS = {"": "Todos", "aberta": "Aberta", "avaliacao": "Avaliação", "aprovada": "Aprovada",
                  "em_andamento": "Em andamento", "entregue": "Entregue", "recusada": "Recusada"}

# Padrao_Barra_de_Filtros: lista FECHADA, nesta ordem, padrão "Mês atual"
PERIODOS = [("mes", "Mês atual"), ("mes_passado", "Mês passado"), ("hoje", "Hoje"),
            ("7d", "Últ. 7 dias"), ("30d", "Últ. 30 dias"), ("custom", "Período customizado")]


def periodo_do_request(args) -> tuple[str, str | None, str | None]:
    """(chave, de, ate) em data LOCAL 'AAAA-MM-DD'. 'todos' = sem filtro (o Limpar).

    Customizado sem datas válidas abre preenchido com o mês atual.
    """
    chave = (args.get("periodo") or "mes").strip()
    hoje = hoje_local()
    ini_mes = hoje.replace(day=1)
    fim_mes = (ini_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if chave == "todos":
        return chave, None, None
    if chave == "mes_passado":
        fim = ini_mes - timedelta(days=1)
        return chave, fim.replace(day=1).isoformat(), fim.isoformat()
    if chave == "hoje":
        return chave, hoje.isoformat(), hoje.isoformat()
    if chave in ("7d", "30d"):
        dias = 7 if chave == "7d" else 30
        return chave, (hoje - timedelta(days=dias - 1)).isoformat(), hoje.isoformat()
    if chave == "custom":
        de, ate = (args.get("de") or "").strip(), (args.get("ate") or "").strip()
        try:
            d1, d2 = datetime.strptime(de, "%Y-%m-%d").date(), datetime.strptime(ate, "%Y-%m-%d").date()
        except ValueError:
            return chave, ini_mes.isoformat(), fim_mes.isoformat()
        if d1 > d2:
            d1, d2 = d2, d1
        return chave, d1.isoformat(), d2.isoformat()
    return "mes", ini_mes.isoformat(), fim_mes.isoformat()

# Upload de fotos da OS: regras de tipo e tamanho em core/upload.py.
# Momentos em que a foto pode ser trocada (foto ANTES na recepção, DEPOIS na execução)
MOMENTOS_FOTO = {
    "antes": ("foto_antes", {"aberta", "avaliacao", "aprovada", "em_andamento"}),
    "depois": ("foto_depois", {"aprovada", "em_andamento"}),
}

CAMPOS_FORM = (
    "id_cliente", "id_equipamento", "patrimonio", "id_tecnico",
    "descricao_inicial", "custo_deslocamento", "status",
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _so_as_proprias() -> bool:
    """Quem não é Administrador enxerga e mexe só nas OS em que é o técnico.

    Antes a regra era "VER sem EDITAR", mas o perfil Técnico tem EDITAR em OS
    (precisa pra foto/execução), então o filtro nunca valia pra ele.
    """
    # escada: perfil 1 fixo (admin blindado, Admin_Inicial_Padrao); virar permissão
    # "os_todas" na matriz se surgir perfil de gestor que não é admin
    return current_user.is_authenticated and current_user.id_perfil != 1


def _filtrar_os_tecnico(sql: str, params: tuple) -> tuple[str, tuple]:
    """Restringe a consulta às OS do técnico logado (a consulta usa o alias `os`)."""
    if _so_as_proprias():
        sql += " AND os.id_tecnico = ?"
        params = params + (current_user.id,)
    return sql, params


def _os_do_usuario(id_os: int, acao: str, colunas: str = "os.*"):
    """Portão único de toda rota com id de OS: permissão + dono.

    OS inexistente e OS de outro técnico devolvem o MESMO 404 (Padrao_IDOR):
    403 confirmaria que o id existe.
    """
    if not current_user.pode("os", acao):
        abort(404)
    sql = f"SELECT {colunas} FROM ordem_servico os WHERE os.id = ? AND os.D_E_L_E_T = 0"
    sql, params = _filtrar_os_tecnico(sql, (id_os,))
    row = query_one(sql, params)
    if row is None:
        log_acesso("ACESSO_NEGADO_IDOR", current_user.id, f"recurso=os id={id_os}")
        abort(404)
    return row


def _gerar_token() -> str:
    return secrets.token_urlsafe(32)


# ──────────────────────────────────────────────────────────────────────────────
# Listagem com filtros (status, tecnico, periodo)
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/")
@login_required
def listar():
    if not current_user.pode("os", "ver"):
        abort(403)

    status = (request.args.get("status") or "").strip()
    if status not in _STATUS_VALIDOS and status != "ativas":   # "ativas" = atalho do Início
        status = ""
    tecnico_id = request.args.get("tecnico", type=int)
    periodo, de, ate = periodo_do_request(request.args)

    sql = """SELECT os.id, os.patrimonio, os.status, os.descricao_inicial,
                    os.orcamento_valor, os.orcamento_status, os.data_abertura,
                    c.razao_social AS cliente,
                    u.nome AS tecnico
             FROM ordem_servico os
             JOIN cliente c ON c.id = os.id_cliente
             LEFT JOIN usuario u ON u.id = os.id_tecnico
             WHERE os.D_E_L_E_T = 0"""
    params: list = []

    if status == "ativas":
        sql += " AND os.status IN ('aberta', 'avaliacao', 'aprovada', 'em_andamento')"
    elif status:
        sql += " AND os.status = ?"
        params.append(status)

    if tecnico_id:
        sql += " AND os.id_tecnico = ?"
        params.append(tecnico_id)

    if de and ate:
        # data_abertura é UTC; os dias do filtro são locais. limites_utc converte
        # o DIA local em faixa UTC (não depende do fuso do servidor, como o
        # 'localtime' do SQLite dependia) e a comparação direta usa o índice.
        ini_utc, fim_utc = limites_utc(date.fromisoformat(de), date.fromisoformat(ate))
        sql += " AND os.data_abertura >= ? AND os.data_abertura < ?"
        params += [ini_utc, fim_utc]

    sql, params = _filtrar_os_tecnico(sql, tuple(params))
    sql += " ORDER BY os.data_abertura DESC"
    linhas = query(sql, params)

    # listas para os filtros da UI
    tecnicos = query(
        """SELECT u.id, u.nome FROM usuario u
           WHERE u.D_E_L_E_T = 0 AND u.id_perfil = 2
           ORDER BY u.nome COLLATE NOCASE"""
    )

    return render_template(
        "os/lista.html",
        oss=[dict(l) for l in linhas],
        tecnicos=[dict(t) for t in tecnicos],
        status_sel=status,
        tecnico_sel=tecnico_id,
        periodo_sel=periodo,
        periodos=PERIODOS,
        periodo_de=de,
        periodo_ate=ate,
        so_as_proprias=_so_as_proprias(),
        rotulos_status={**ROTULOS_STATUS, "ativas": "Em aberto (todas)"},
        status_opcoes=[{"valor": "", "rotulo": "Todos"}, {"valor": "ativas", "rotulo": "Em aberto (todas)"}]
                      + [{"valor": s, "rotulo": ROTULOS_STATUS[s]} for s in ORDEM_STATUS],
        tecnicos_opcoes=[{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos],
        pode_editar=current_user.pode("os", "editar"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Abertura de OS
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    if not current_user.pode("os", "editar"):
        abort(403)

    equipamentos = query(
        """SELECT e.id, e.patrimonio, e.modelo, c.razao_social
             FROM equipamento e
             JOIN cliente c ON c.id = e.id_cliente
            WHERE e.D_E_L_E_T = 0
            ORDER BY c.razao_social, e.patrimonio"""
    )
    tecnicos = query(
        """SELECT u.id, u.nome FROM usuario u
           WHERE u.D_E_L_E_T = 0 AND u.id_perfil = 2
           ORDER BY u.nome COLLATE NOCASE"""
    )
    eq_opcoes = [{"valor": e["id"],
                  "rotulo": f'{e["patrimonio"]} · {e["modelo"] or "sem modelo"}',
                  "sub": e["razao_social"]} for e in equipamentos]
    tec_opcoes = [{"valor": t["id"], "rotulo": t["nome"]} for t in tecnicos]

    def tela(erros: dict, valores: dict, codigo: int = 200):
        """Re-renderiza com os rótulos dos SelectBusca já preenchidos (erro 422 inclusive)."""
        def rotulo(opcoes, valor):
            return next((o["rotulo"] for o in opcoes if str(o["valor"]) == str(valor or "")), "")
        cli = None
        if (valores.get("id_cliente") or "").isdigit():
            cli = query_one("SELECT razao_social FROM cliente WHERE id = ? AND D_E_L_E_T = 0",
                            (int(valores["id_cliente"]),))
        return render_template(
            "os/nova.html",
            equipamentos_opcoes=eq_opcoes,
            tecnicos_opcoes=tec_opcoes,
            so_as_proprias=_so_as_proprias(),
            cliente_rotulo=cli["razao_social"] if cli else "",
            equipamento_rotulo=rotulo(eq_opcoes, valores.get("id_equipamento")),
            tecnico_rotulo=rotulo(tec_opcoes, valores.get("id_tecnico")),
            erros=erros,
            valores=valores,
        ), codigo

    if request.method == "GET":
        return tela({}, {})

    valores = {k: (request.form.get(k) or "").strip() for k in CAMPOS_FORM}
    erros: dict[str, str] = {}

    dados = None
    try:
        dados = OSIn(**valores)
    except Exception as exc:  # pydantic.ValidationError
        mensagens = exc.errors() if hasattr(exc, "errors") else [{"msg": str(exc)}]
        for item in mensagens:
            campo = (item.get("loc") or ["formulario"])[0] if isinstance(item, dict) else "formulario"
            erros[str(campo)] = item.get("msg", str(item))

    # verifica existencia de cliente/equipamento
    if dados is not None:
        if not dados.id_cliente:
            erros["id_cliente"] = "Escolha o cliente na lista."
        elif not query_one(
            "SELECT id FROM cliente WHERE id = ? AND D_E_L_E_T = 0", (dados.id_cliente,)
        ):
            erros["id_cliente"] = "Cliente não encontrado."
        if dados.id_equipamento and not query_one(
            "SELECT id FROM equipamento WHERE id = ? AND D_E_L_E_T = 0", (dados.id_equipamento,)
        ):
            erros["id_equipamento"] = "Equipamento não encontrado."
        if dados.id_tecnico and not query_one(
            "SELECT id FROM usuario WHERE id = ? AND id_perfil = 2 AND D_E_L_E_T = 0",
            (dados.id_tecnico,),
        ):
            erros["id_tecnico"] = "Técnico não encontrado."

    if erros:
        return tela(erros, valores, 422)

    linhas = dados.para_linhas()
    # Técnico abre OS sempre pra si: o id_tecnico do form só vale pro Administrador
    if _so_as_proprias():
        linhas["id_tecnico"] = current_user.id
    # patrimonio nao pode ser None (coluna NOT NULL); vazio vira string vazia
    if linhas.get("patrimonio") is None:
        linhas["patrimonio"] = ""

    try:
        with transaction() as db:
            # INSERT sem patrimonio (gerado apos conhecer o id)
            cols = ", ".join(linhas)
            marcadores = ", ".join("?" for _ in linhas)
            cur = db.execute(
                f"INSERT INTO ordem_servico ({cols}) VALUES ({marcadores})",
                tuple(linhas.values()),
            )
            id_os = cur.lastrowid

            # Regra do patrimonio: se vazio, gera ESG{idOS}
            if not linhas.get("patrimonio"):
                db.execute(
                    "UPDATE ordem_servico SET patrimonio = ? WHERE id = ?",
                    (f"ESG{id_os}", id_os),
                )
    except sqlite3.IntegrityError:
        flash("Não foi possível abrir a OS.", "erro")
        return redirect(url_for("os.listar"))

    flash(f"OS #{id_os} aberta. Patrimônio: {linhas.get('patrimonio') or f'ESG{id_os}'}.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


# ──────────────────────────────────────────────────────────────────────────────
# Detalhe da OS
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/<int:id_os>")
@login_required
def detalhe(id_os: int):
    _os_do_usuario(id_os, "ver", "os.id")   # permissão + dono, 404 igual pros dois

    sql = """SELECT os.*, c.razao_social AS cliente, c.cidade, c.uf,
                    u.nome AS tecnico_nome
             FROM ordem_servico os
             JOIN cliente c ON c.id = os.id_cliente
             LEFT JOIN usuario u ON u.id = os.id_tecnico
             WHERE os.id = ? AND os.D_E_L_E_T = 0"""
    os_row = query_one(sql, (id_os,))

    itens = query(
        """SELECT i.id, i.id_peca, i.descricao, i.quantidade,
                  i.preco_unitario, i.subtotal, p.codigo AS peca_codigo
             FROM item_os i
             LEFT JOIN peca p ON p.id = i.id_peca
            WHERE i.id_os = ? AND i.D_E_L_E_T = 0
            ORDER BY i.id""",
        (id_os,),
    )

    # Link de aprovação: só faz sentido mostrar se o token ainda está vivo.
    # url_for não aceita token=None (Werkzeug ignora valor None e o BuildError
    # derruba a tela), então o link só é montado quando existe token vivo.
    token_valido = False
    link_publico = None
    if os_row["os_token"] and os_row["token_expira"]:
        token_valido = not _token_vencido(os_row["token_expira"])
        if token_valido:
            link_publico = url_for(
                "os.publico", token=os_row["os_token"], _external=True
            )

    return render_template(
        "os/detalhe.html",
        os=dict(os_row),
        itens=[dict(i) for i in itens],
        pode_editar=current_user.pode("os", "editar"),
        pode_ver=current_user.pode("os", "ver"),
        token_valido=token_valido,
        link_publico=link_publico,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fotos ANTES/DEPOIS, execução e entrega (checklist 135 e 139)
# ──────────────────────────────────────────────────────────────────────────────

def _carrega_os_para_edicao(id_os: int):
    """Carrega a OS exigindo EDITAR e dono; senão 404."""
    return _os_do_usuario(
        id_os, "editar",
        "os.id, os.status, os.foto_antes, os.foto_depois, "
        "os.descricao_execucao, os.testado_funcionamento, os.entrega_solicitada_em",
    )


def _processar_foto() -> tuple[str | None, str | None]:
    """Valida e salva a foto em static/uploads/os/.

    Devolve (caminho_relativo, erro). Erro vira mensagem de campo, nunca 500.
    """
    arq = request.files.get("foto")
    if not arq or not arq.filename:
        return None, "Escolha uma imagem (JPG, PNG ou WEBP, até 5 MB)."
    return salvar_imagem(arq, "os")


def _apaga_foto(relativo: str | None) -> None:
    """Apaga a foto antiga (best effort: foto sumida não derruba o save)."""
    if not relativo or not relativo.startswith("uploads/"):
        return
    try:
        (Path(current_app.root_path) / "static" / relativo).unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning("FOTO_NAO_APAGADA %s", relativo)


@os_bp.route("/<int:id_os>/foto", methods=["POST"])
@login_required
def foto(id_os: int):
    """Troca a foto ANTES ou DEPOIS da OS (drag-drop do .im-drop)."""
    os_row = _carrega_os_para_edicao(id_os)

    momento = (request.form.get("momento") or "").strip()
    if momento not in MOMENTOS_FOTO:
        flash("Momento da foto inválido.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    coluna, status_permitidos = MOMENTOS_FOTO[momento]
    if os_row["status"] not in status_permitidos:
        flash("Não é possível trocar esta foto nesta etapa da OS.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    relativo, erro = _processar_foto()
    if erro:
        flash(erro, "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    antiga = os_row[coluna]
    with transaction() as db:
        # coluna vem de MOMENTOS_FOTO (dict fechado), mas o UPDATE é explícito
        # de propósito: nada de SQL montado com nome de coluna variável.
        if momento == "antes":
            db.execute(
                "UPDATE ordem_servico SET foto_antes = ? WHERE id = ?",
                (relativo, id_os),
            )
        else:
            # Foto nova invalida o pedido de entrega: o cliente confirmaria a foto velha
            db.execute(
                "UPDATE ordem_servico SET foto_depois = ?, entrega_solicitada_em = NULL WHERE id = ?",
                (relativo, id_os),
            )
    if antiga:
        _apaga_foto(antiga)

    flash(f"Foto {'ANTES' if momento == 'antes' else 'DEPOIS'} salva.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


@os_bp.route("/<int:id_os>/execucao", methods=["POST"])
@login_required
def execucao(id_os: int):
    """Registra o que o técnico fez + se testou o funcionamento.

    Só depois da aprovação: sem orçamento aprovado não existe execução.
    """
    os_row = _carrega_os_para_edicao(id_os)
    if os_row["status"] not in ("aprovada", "em_andamento"):
        flash("A execução começa depois que o cliente aprova o orçamento.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    descricao = (request.form.get("descricao_execucao") or "").strip()
    testado = 1 if request.form.get("testado_funcionamento") else 0

    if len(descricao) < 5:
        flash("Descreva o que foi feito (mínimo 5 caracteres).", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))
    if not os_row["foto_depois"]:
        flash("Envie a foto DEPOIS antes de registrar a execução.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    with transaction() as db:
        db.execute(
            """UPDATE ordem_servico
                  SET descricao_execucao = ?, testado_funcionamento = ?,
                      status = 'em_andamento', entrega_solicitada_em = NULL,
                      data_inicio = COALESCE(data_inicio, CURRENT_TIMESTAMP)
                WHERE id = ?""",
            (descricao, testado, id_os),
        )
    flash("Execução registrada.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


@os_bp.route("/<int:id_os>/entregar", methods=["POST"])
@login_required
def entregar(id_os: int):
    """Pede a validação da entrega: exige foto DEPOIS, execução e o teste."""
    os_row = _carrega_os_para_edicao(id_os)
    if os_row["status"] != "em_andamento":
        flash("Esta OS não está em execução.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    faltas = []
    if not os_row["foto_depois"]:
        faltas.append("foto DEPOIS")
    if not (os_row["descricao_execucao"] or "").strip():
        faltas.append("descrição do serviço")
    if not os_row["testado_funcionamento"]:
        faltas.append("teste de funcionamento")
    if faltas:
        flash("Falta para entregar: " + ", ".join(faltas) + ".", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    # Quem fecha a OS é o CLIENTE, pelo link: o técnico só pede. Link novo a
    # cada pedido (o da aprovação pode ter vencido ou ter ido pra outra pessoa).
    with transaction() as db:
        _renova_token(db, id_os)
        db.execute(
            "UPDATE ordem_servico SET entrega_solicitada_em = CURRENT_TIMESTAMP WHERE id = ?",
            (id_os,),
        )
    flash("Pedido de validação criado. Envie o link ao cliente: ele confere o serviço, "
          "assina e confirma ENTREGUE.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


def _renova_token(db, id_os: int) -> None:
    """Gera token público novo com a validade da configuracao (padrão 7 dias)."""
    row = db.execute(
        "SELECT valor FROM configuracao WHERE chave = 'os_token_expira_dias'"
    ).fetchone()
    dias = int(row["valor"]) if row and str(row["valor"]).isdigit() else 7
    db.execute(
        "UPDATE ordem_servico SET os_token = ?, token_expira = ? WHERE id = ?",
        (_gerar_token(), agora_utc_texto(timedelta(days=dias)), id_os),
    )


def _token_vencido(expira) -> bool:
    """Validade do link em UTC (core/tempo). Valor ilegível conta como vencido."""
    dt = ler_utc(expira)
    return dt is None or agora_utc() > dt


def _baixa_estoque(db, id_os: int) -> None:
    """Na ENTREGA, as peças do estoque usadas na OS saem do estoque.

    Recusa nunca chega aqui: OS recusada não baixa peça (só o deslocamento é
    cobrado). Item digitado livre (sem id_peca) não tem o que baixar.
    O saldo pode ficar negativo de propósito: a peça já foi usada, e o negativo
    acusa o erro de inventário em vez de esconder.
    """
    itens = db.execute(
        "SELECT id_peca, quantidade FROM item_os "
        "WHERE id_os = ? AND id_peca IS NOT NULL AND D_E_L_E_T = 0",
        (id_os,),
    ).fetchall()
    for it in itens:
        qtd = float(it["quantidade"] or 0)
        if qtd <= 0:
            continue
        db.execute(
            "UPDATE peca SET estoque_atual = COALESCE(estoque_atual, 0) - ? WHERE id = ?",
            (qtd, it["id_peca"]),
        )
        db.execute(
            """INSERT INTO movimento_estoque
                   (id_peca, tipo, quantidade, id_origem, origem_tipo, observacoes)
               VALUES (?, 'SAIDA', ?, ?, 'OS', ?)""",
            (it["id_peca"], qtd, id_os, f"Entrega da OS #{id_os}"),
        )


ASSINATURA_MAX = 400_000  # caracteres do data URL (~300 KB de PNG)


def _assinatura_valida(dado: str) -> str | None:
    """Aceita só data URL de PNG de verdade (magic bytes), com teto de tamanho.

    O valor volta pra tela em <img src>: qualquer coisa fora de PNG em base64
    seria vetor de XSS, então o resto é recusado.
    """
    prefixo = "data:image/png;base64,"
    if not dado or not dado.startswith(prefixo) or len(dado) > ASSINATURA_MAX:
        return None
    corpo = dado[len(prefixo):]
    try:
        bruto = base64.b64decode(corpo, validate=True)
    except (binascii.Error, ValueError):
        return None
    if tipo_real_imagem(bruto[:12]) != "png" or len(bruto) < 200:
        return None
    return prefixo + corpo


# ──────────────────────────────────────────────────────────────────────────────
# Adicionar item de peca à OS
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/<int:id_os>/item", methods=["POST"])
@login_required
def adicionar_item(id_os: int):
    os_row = _os_do_usuario(id_os, "editar", "os.id, os.status")
    if os_row["status"] not in ("aberta", "avaliacao"):
        flash("Não é possível adicionar itens nesta etapa da OS.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    valores = {k: (request.form.get(k) or "").strip() for k in ("id_peca", "descricao", "quantidade", "preco_unitario")}
    erros: dict[str, str] = {}

    try:
        dados = ItemOSIn(**valores)
    except Exception as exc:
        mensagens = exc.errors() if hasattr(exc, "errors") else [{"msg": str(exc)}]
        for item in mensagens:
            campo = (item.get("loc") or ["formulario"])[0] if isinstance(item, dict) else "formulario"
            erros[str(campo)] = item.get("msg", str(item))

    if erros:
        flash("Item inválido: " + "; ".join(erros.values()), "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    linhas = dados.para_linhas()
    subtotal = float(linhas.get("quantidade") or 1) * float(linhas.get("preco_unitario") or 0)
    linhas["subtotal"] = f"{subtotal:.2f}"

    try:
        with transaction() as db:
            db.execute(
                """INSERT INTO item_os
                       (id_os, id_peca, descricao, quantidade, preco_unitario, subtotal)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (id_os,
                 linhas.get("id_peca"),
                 linhas.get("descricao"),
                 linhas.get("quantidade"),
                 linhas.get("preco_unitario"),
                 linhas.get("subtotal")),
            )
            recalcula_orcamento(db, id_os)
    except sqlite3.Error:
        flash("Erro ao adicionar item à OS.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    flash("Item adicionado à OS.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


@os_bp.route("/<int:id_os>/item/<int:id_item>/remover", methods=["POST"])
@login_required
def remover_item(id_os: int, id_item: int):
    """Tira item lançado errado. Só antes da aprovação: depois, o cliente já
    aprovou aquele valor e mexer nele seria mudar o combinado."""
    os_row = _os_do_usuario(id_os, "editar", "os.id, os.status")
    if os_row["status"] not in ("aberta", "avaliacao"):
        flash("Depois da aprovação os itens não mudam mais.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))
    with transaction() as db:
        # id_os no WHERE: id de item de OUTRA OS não é removido por aqui (IDOR)
        cur = db.execute(
            "UPDATE item_os SET D_E_L_E_T = 1 WHERE id = ? AND id_os = ? AND D_E_L_E_T = 0",
            (id_item, id_os),
        )
        if cur.rowcount != 1:
            abort(404)
        recalcula_orcamento(db, id_os)
    flash("Item removido. O valor do orçamento foi recalculado.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


def recalcula_orcamento(db, id_os: int) -> None:
    """Orçamento = soma dos itens. O valor é sempre derivado no servidor.

    Antes era digitado na abertura e ficava solto dos itens: o cliente aprovava
    um número que não era a soma do que via na tela. Mão de obra entra como item.
    Deslocamento fica à parte (é cobrado mesmo na recusa).
    """
    db.execute(
        """UPDATE ordem_servico
              SET orcamento_valor = (SELECT COALESCE(SUM(subtotal), 0) FROM item_os
                                      WHERE id_os = ? AND D_E_L_E_T = 0)
            WHERE id = ?""",
        (id_os, id_os),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Link público do cliente: ver status e aprovar/recusar orçamento
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/public/<token>", methods=["GET", "POST"])
def publico(token: str):
    os_row = query_one(
        """SELECT os.id, os.patrimonio, os.status, os.orcamento_status,
                  os.orcamento_valor, os.custo_deslocamento,
                  os.descricao_inicial, os.descricao_execucao, os.testado_funcionamento,
                  os.foto_depois, os.entrega_solicitada_em, os.assinatura_cliente,
                  os.data_entrega, os.data_abertura, os.token_expira,
                  c.razao_social AS cliente, c.cidade, c.uf
             FROM ordem_servico os
             JOIN cliente c ON c.id = os.id_cliente
            WHERE os.os_token = ? AND os.D_E_L_E_T = 0""",
        (token,),
    )
    if os_row is None:
        abort(404)

    if os_row["token_expira"] and _token_vencido(os_row["token_expira"]):
        return render_template("os/publico_expirado.html", os=dict(os_row), pagina_publica=True), 410

    aguarda_entrega = (os_row["status"] == "em_andamento" and bool(os_row["entrega_solicitada_em"]))

    if request.method == "POST" and (request.form.get("decisao") or "") == "entregue":
        # Validação ENTREGUE: só quando o técnico pediu, com assinatura de verdade
        if not aguarda_entrega:
            abort(400)
        assinatura = _assinatura_valida(request.form.get("assinatura") or "")
        if assinatura is None:
            flash("Assine no quadro antes de confirmar a entrega.", "erro")
            return redirect(url_for("os.publico", token=token))
        with transaction() as db:
            # status no WHERE: dois cliques não baixam o estoque duas vezes
            cur = db.execute(
                """UPDATE ordem_servico
                      SET status = 'entregue', data_entrega = CURRENT_TIMESTAMP,
                          assinatura_cliente = ?
                    WHERE id = ? AND status = 'em_andamento'
                      AND entrega_solicitada_em IS NOT NULL""",
                (assinatura, os_row["id"]),
            )
            if cur.rowcount == 1:
                _baixa_estoque(db, os_row["id"])
                # Fase 7: entregue gera o recebível (orçamento + deslocamento) na
                # MESMA transação. Import local: financeiro importa deste módulo.
                from modules.financeiro import gerar_recebivel_os
                gerar_recebivel_os(db, os_row["id"], "entregue")
        if cur.rowcount == 1:
            log_acesso("OS_ENTREGUE_CLIENTE", None, f"os={os_row['id']}")
            flash("Entrega confirmada. Obrigado!", "sucesso")
        return redirect(url_for("os.publico", token=token))

    if request.method == "POST" and os_row["orcamento_status"] == "pendente":
        # Nome ASCII no form (decisao): nome de campo com acento não sobrevive
        # ao POST do navegador. O nome antigo continua aceito pra não quebrar
        # quem já manda assim.
        decisão = (
            request.form.get("decisao") or request.form.get("decisão") or ""
        ).strip().lower()
        if decisão not in ("aprovar", "recusar"):
            abort(400)
        with transaction() as db:
            novo = "aprovado" if decisão == "aprovar" else "recusado"
            db.execute(
                """UPDATE ordem_servico
                       SET orcamento_status = ?,
                           data_aprovacao = CASE WHEN ? = 'aprovado' THEN CURRENT_TIMESTAMP ELSE data_aprovacao END,
                           data_recusa = CASE WHEN ? = 'recusado' THEN CURRENT_TIMESTAMP ELSE data_recusa END
                     WHERE id = ?""",
                (novo, novo, novo, os_row["id"]),
            )
            if novo == "aprovado":
                db.execute(
                    "UPDATE ordem_servico SET status = 'aprovada' WHERE id = ?",
                    (os_row["id"],),
                )
            else:
                db.execute(
                    "UPDATE ordem_servico SET status = 'recusada' WHERE id = ?",
                    (os_row["id"],),
                )
                # Recusa cobra só o deslocamento (quando houver)
                from modules.financeiro import gerar_recebivel_os
                gerar_recebivel_os(db, os_row["id"], "recusada")
        log_acesso("OS_ORCAMENTO_" + novo.upper(), None, f"os={os_row['id']}")
        flash(f"Orçamento {novo} registrado com sucesso.", "sucesso")
        return redirect(url_for("os.publico", token=token))

    if request.method == "POST":
        abort(400)   # decisão fora da etapa (ex.: aprovar de novo, entregar sem pedido)

    itens = query(
        """SELECT i.descricao, i.quantidade, i.preco_unitario, i.subtotal
             FROM item_os i
            WHERE i.id_os = ? AND i.D_E_L_E_T = 0
            ORDER BY i.id""",
        (os_row["id"],),
    )
    return render_template(
        "os/publico.html",
        os=dict(os_row),
        itens=[dict(i) for i in itens],
        aguarda_entrega=aguarda_entrega,
        token=token,
        pagina_publica=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gerar token de aprovacao (tecnico/admin envia link ao cliente)
# ──────────────────────────────────────────────────────────────────────────────

@os_bp.route("/<int:id_os>/token", methods=["POST"])
@login_required
def gerar_token(id_os: int):
    os_row = _os_do_usuario(id_os, "editar", "os.id, os.orcamento_status")
    if os_row["orcamento_status"] not in ("pendente", "recusado"):
        flash("Token só pode ser gerado para orçamento pendente ou recusado.", "erro")
        return redirect(url_for("os.detalhe", id_os=id_os))

    with transaction() as db:
        _renova_token(db, id_os)
        db.execute(
            "UPDATE ordem_servico SET status = 'avaliacao' WHERE id = ?",
            (id_os,),
        )

    flash("Link de aprovação gerado. Copie ou envie pelo WhatsApp no card abaixo.", "sucesso")
    return redirect(url_for("os.detalhe", id_os=id_os))


# ──────────────────────────────────────────────────────────────────────────────
# Comprovante da OS (Imprimir / Salvar PDF) e cancelamento
# ──────────────────────────────────────────────────────────────────────────────
# escada: o plano pedia WeasyPrint, que no Windows exige o runtime GTK instalado.
# A tela de impressão + "Salvar como PDF" do navegador entrega o mesmo PDF sem
# dependência nova. Volta pra WeasyPrint se precisar ANEXAR o PDF por e-mail
# automático (aí o servidor tem que gerar o arquivo sozinho).

def _comprovante(id_os: int, publico: bool):
    os_row = query_one(
        """SELECT os.*, c.razao_social AS cliente, c.cidade, c.uf, c.telefone1,
                  u.nome AS tecnico_nome
             FROM ordem_servico os
             JOIN cliente c ON c.id = os.id_cliente
             LEFT JOIN usuario u ON u.id = os.id_tecnico
            WHERE os.id = ? AND os.D_E_L_E_T = 0""",
        (id_os,),
    )
    if os_row is None:
        abort(404)
    itens = query(
        """SELECT descricao, quantidade, preco_unitario, subtotal
             FROM item_os WHERE id_os = ? AND D_E_L_E_T = 0 ORDER BY id""",
        (id_os,),
    )
    soma_itens = sum(float(i["subtotal"] or 0) for i in itens)
    empresa = query_one("SELECT valor FROM configuracao WHERE chave = 'empresa_nome'")
    return render_template(
        "os/comprovante.html",
        os=dict(os_row),
        itens=[dict(i) for i in itens],
        soma_itens=soma_itens,
        empresa=(empresa["valor"] if empresa else "OficinaApp"),
        publico=publico,
        emitido=agora_local().strftime("%d/%m/%Y %H:%M"),
    )


@os_bp.route("/<int:id_os>/comprovante")
@login_required
def comprovante(id_os: int):
    _os_do_usuario(id_os, "ver", "os.id")
    return _comprovante(id_os, publico=False)


@os_bp.route("/public/<token>/comprovante")
def comprovante_publico(token: str):
    row = query_one(
        "SELECT id, token_expira FROM ordem_servico WHERE os_token = ? AND D_E_L_E_T = 0",
        (token,),
    )
    if row is None:
        abort(404)
    if row["token_expira"] and _token_vencido(row["token_expira"]):
        abort(404)
    return _comprovante(row["id"], publico=True)


@os_bp.route("/<int:id_os>/cancelar", methods=["POST"])
@login_required
def cancelar(id_os: int):
    """Cancela OS que ainda não foi aprovada (soft delete; o link público morre junto)."""
    os_row = _os_do_usuario(id_os, "editar", "os.id, os.status")
    if os_row["status"] not in ("aberta", "avaliacao"):
        flash("Só dá pra cancelar OS aberta ou em avaliação: depois da aprovação ela segue o fluxo.", "erro")
        return redirect(url_for("os.listar"))
    with transaction() as db:
        db.execute(
            "UPDATE ordem_servico SET D_E_L_E_T = 1, deleted_at = CURRENT_TIMESTAMP, "
            "       os_token = NULL, token_expira = NULL WHERE id = ?",
            (id_os,),
        )
    log_acesso("OS_CANCELADA", current_user.id, f"os={id_os}")
    flash(f"OS #{id_os} cancelada.", "sucesso")
    return redirect(url_for("os.listar"))