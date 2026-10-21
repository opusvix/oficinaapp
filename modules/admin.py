"""Administração: perfis e matriz de permissões VER/EDITAR.

Regras da matriz (Matriz_VER_EDITAR):
  - EDITAR implica VER (servidor força, não confia no checkbox).
  - Admin (perfil 1) mantém sempre auth + perfis: senão se tranca fora.
  - Ninguém tira perfis do próprio perfil (trava de porta na própria mão).
"""
from __future__ import annotations

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

from core.db import get_db, query, query_one

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Perfil 1 não perde a chave da porta (auth = usuários, perfis = permissões)
PROTEGIDOS_ADMIN = ("auth", "perfis")


def _protege(id_perfil: int, chave: str) -> bool:
    if id_perfil == 1 and chave in PROTEGIDOS_ADMIN:
        return True
    if id_perfil == current_user.id_perfil and chave == "perfis":
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Listagem de perfis
# ──────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/perfis")
@login_required
def perfis():
    if not current_user.pode("perfis", "ver"):
        abort(403)

    linhas = query(
        """SELECT p.id, p.nome, p.descricao,
                  (SELECT COUNT(*) FROM usuario u
                    WHERE u.id_perfil = p.id AND u.D_E_L_E_T = 0) AS qtd_usuarios,
                  (SELECT COUNT(*) FROM permissoes pe
                     JOIN modulo m ON m.id = pe.id_modulo
                    WHERE pe.id_perfil = p.id AND pe.D_E_L_E_T = 0
                      AND m.D_E_L_E_T = 0 AND pe.pode_ver = 1) AS qtd_ver,
                  (SELECT COUNT(*) FROM permissoes pe
                     JOIN modulo m ON m.id = pe.id_modulo
                    WHERE pe.id_perfil = p.id AND pe.D_E_L_E_T = 0
                      AND m.D_E_L_E_T = 0 AND pe.pode_editar = 1) AS qtd_editar
             FROM perfil p
            WHERE p.D_E_L_E_T = 0
            ORDER BY p.id"""
    )
    total_modulos = query_one(
        "SELECT COUNT(*) AS n FROM modulo WHERE D_E_L_E_T = 0"
    )["n"]
    pode_editar = current_user.pode("perfis", "editar")
    return render_template(
        "admin/perfis.html", perfis=linhas, total_modulos=total_modulos, pode_editar=pode_editar
    )


# ──────────────────────────────────────────────────────────────────────────────
# Matriz VER / EDITAR
# ──────────────────────────────────────────────────────────────────────────────

def _carregar(id_perfil: int):
    perfil = query_one("SELECT id, nome, descricao FROM perfil WHERE id = ? AND D_E_L_E_T = 0", (id_perfil,))
    if perfil is None:
        abort(404)

    atuais = {
        r["id_modulo"]: (bool(r["pode_ver"]), bool(r["pode_editar"]))
        for r in query(
            """SELECT id_modulo, pode_ver, pode_editar FROM permissoes
                WHERE id_perfil = ? AND D_E_L_E_T = 0""",
            (id_perfil,),
        )
    }

    autos = {
        r["grupo"]: (bool(r["auto_ver"]), bool(r["auto_editar"]))
        for r in query("SELECT grupo, auto_ver, auto_editar FROM perfis_grupos_auto "
                       "WHERE id_perfil = ? AND D_E_L_E_T = 0", (id_perfil,))
    }

    grupos: dict[str, list[dict]] = {}
    ordem: list[str] = []
    for m in query("SELECT id, chave, nome, grupo, icone, em_breve FROM modulo WHERE D_E_L_E_T = 0 ORDER BY id"):
        ver, editar = atuais.get(m["id"], (False, False))
        nome_grupo = m["grupo"] or "Outros"
        if nome_grupo not in grupos:
            grupos[nome_grupo] = []
            ordem.append(nome_grupo)
        grupos[nome_grupo].append(
            {
                "id": m["id"],
                "chave": m["chave"],
                "nome": m["nome"],
                "icone": m["icone"] or "ph-squares-four",
                "em_breve": bool(m["em_breve"]),
                "ver": ver,
                "editar": editar,
                "protegido": _protege(id_perfil, m["chave"]),
            }
        )

    return perfil, [{"nome": g, "modulos": grupos[g],
                     "auto_ver": autos.get(g, (False, False))[0],
                     "auto_editar": autos.get(g, (False, False))[1]} for g in ordem]


@admin_bp.route("/perfis/<int:id_perfil>/permissoes", methods=["GET", "POST"])
@login_required
def perfis_permissoes(id_perfil: int):
    perfil, grupos = _carregar(id_perfil)

    if request.method == "POST":
        if not current_user.pode("perfis", "editar"):
            abort(403)

        db = get_db()
        # UPSERT por módulo, nunca DELETE (Nunca_DELETE_Fisico): o módulo que sai
        # da matriz vira linha pode_ver=0/pode_editar=0 (pode() trata como sem acesso),
        # em vez de o registro ser apagado. O DELETE antigo perdia o histórico.
        alteradas = 0
        for grupo in grupos:
            for m in grupo["modulos"]:
                ver = 1 if request.form.get(f"ver_{m['id']}") else 0
                editar = 1 if request.form.get(f"editar_{m['id']}") else 0
                if editar:
                    ver = 1  # EDITAR implica VER
                if _protege(id_perfil, m["chave"]):
                    ver = editar = 1
                db.execute(
                    """INSERT INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar, D_E_L_E_T)
                           VALUES (?, ?, ?, ?, 0)
                       ON CONFLICT(id_perfil, id_modulo)
                       DO UPDATE SET pode_ver = excluded.pode_ver,
                                     pode_editar = excluded.pode_editar, D_E_L_E_T = 0""",
                    (id_perfil, m["id"], ver, editar),
                )
                if ver or editar:
                    alteradas += 1
        # Auto-liberação por grupo: dois toggles por grupo (grupo_<i> + autover_/autoeditar_)
        for gi, grupo in enumerate(grupos):
            nome_grupo = grupo["nome"]
            auto_editar = 1 if request.form.get(f"autoeditar_{gi}") else 0
            auto_ver = 1 if (request.form.get(f"autover_{gi}") or auto_editar) else 0
            db.execute(
                """INSERT INTO perfis_grupos_auto (id_perfil, grupo, auto_ver, auto_editar, D_E_L_E_T)
                       VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(id_perfil, grupo)
                   DO UPDATE SET auto_ver = excluded.auto_ver, auto_editar = excluded.auto_editar, D_E_L_E_T = 0""",
                (id_perfil, nome_grupo, auto_ver, auto_editar),
            )
        db.commit()
        from core.auth import aplicar_auto_liberacoes
        aplicar_auto_liberacoes()   # pega modulo deste grupo que ainda nao tinha linha
        flash(f"Permissões de “{perfil['nome']}” salvas ({alteradas} módulos liberados).", "sucesso")
        return redirect(url_for("admin.perfis_permissoes", id_perfil=id_perfil))

    return render_template(
        "admin/perfis_permissoes.html",
        perfil=perfil,
        grupos=grupos,
        total_modulos=sum(len(g["modulos"]) for g in grupos),
        liberados=sum(1 for g in grupos for m in g["modulos"] if m["ver"]),
        pode_editar=current_user.pode("perfis", "editar"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Usuários (Fase 9). Cadastro MANUAL: 1 admin + poucos técnicos, decisão do DIA 4
# (Padrao_Convite_de_Acesso: convite só vale pra time grande). Regras:
#   - Senha sorteada, mostrada UMA vez na resposta do POST (nunca em flash, que vai
#     no cookie de sessão), e a pessoa é obrigada a trocar no 1º acesso
#     (security.init_troca_obrigatoria). O admin nunca escolhe senha de ninguém.
#   - Nada é apagado: desativar tira o acesso na hora (auth.load_user filtra ativo).
#   - Ninguém desativa nem muda o perfil de si mesmo; o admin id 1 é blindado
#     (Admin_Inicial_Padrao).
# ──────────────────────────────────────────────────────────────────────────────

import secrets as _secrets
import string as _string

import bcrypt as _bcrypt
from pydantic import ValidationError as _ValidationError

from core.auditoria import log_acesso
from modules.validacao_usuario import PERFIL_CLIENTE, UsuarioIn

ADMIN_BLINDADO = 1
_ALFABETO = (_string.ascii_letters + _string.digits).translate(str.maketrans("", "", "0O1lI"))


def _senha_sorteada() -> str:
    return "".join(_secrets.choice(_ALFABETO) for _ in range(14))


def _hash(senha: str) -> str:
    return _bcrypt.hashpw(senha.encode(), _bcrypt.gensalt()).decode()


def _quando(epoch) -> str:
    """logs_acesso.quando (epoch) -> 'dd/mm/aaaa hh:mm' na hora local."""
    if not epoch:
        return "nunca entrou"
    from datetime import datetime
    from core.tempo import FUSO
    return datetime.fromtimestamp(int(epoch), FUSO).strftime("%d/%m/%Y %H:%M")


def _perfis_internos() -> list[dict]:
    return [dict(p) for p in query("SELECT id, nome FROM perfil WHERE D_E_L_E_T = 0 AND id <> ? ORDER BY id",
                                   (PERFIL_CLIENTE,))]


def _tela_usuarios(senha_nova: dict | None = None, erros: dict | None = None, valores: dict | None = None):
    linhas = query(
        """SELECT u.id, u.nome, u.email, u.id_perfil, u.ativo, u.precisa_trocar_senha, p.nome AS perfil,
                  (SELECT MAX(l.quando) FROM logs_acesso l WHERE l.id_usuario = u.id AND l.acao = 'LOGIN') AS ultimo_login
             FROM usuario u JOIN perfil p ON p.id = u.id_perfil
            WHERE u.D_E_L_E_T = 0
            ORDER BY u.ativo DESC, u.nome COLLATE NOCASE""")
    perfis = _perfis_internos()
    return render_template(
        "admin/usuarios.html", usuarios=[{**dict(l), "ultimo_login_fmt": _quando(l["ultimo_login"])} for l in linhas],
        perfis_opcoes=[{"valor": p["id"], "rotulo": p["nome"]} for p in perfis],
        pode_editar=current_user.pode("auth", "editar"), eu=current_user.id, blindado=ADMIN_BLINDADO,
        senha_nova=senha_nova, erros=erros or {}, valores=valores or {},
    )


@admin_bp.route("/usuarios")
@login_required
def usuarios():
    if not current_user.pode("auth", "ver"):
        abort(403)
    return _tela_usuarios()


@admin_bp.route("/usuarios/salvar", methods=["POST"])
@login_required
def usuario_salvar():
    if not current_user.pode("auth", "editar"):
        abort(403)
    id_usuario = request.form.get("id", type=int)
    valores = {k: (request.form.get(k) or "").strip() for k in ("nome", "email", "id_perfil")}
    try:
        dados = UsuarioIn(**valores)
    except _ValidationError as exc:
        erros = {str(e["loc"][0]): str(e["msg"]).replace("Value error, ", "") for e in exc.errors()}
        return _tela_usuarios(erros=erros, valores={**valores, "id": id_usuario or ""}), 422
    perfil = int(dados.id_perfil)
    if not query_one("SELECT 1 FROM perfil WHERE id = ? AND D_E_L_E_T = 0", (perfil,)):
        return _tela_usuarios(erros={"id_perfil": "Perfil não encontrado."}, valores=valores), 422
    db = get_db()
    dono_email = query_one("SELECT id FROM usuario WHERE email = ?", (dados.email,))
    if dono_email and dono_email["id"] != id_usuario:
        return _tela_usuarios(erros={"email": "Já existe usuário com este e-mail."},
                              valores={**valores, "id": id_usuario or ""}), 422

    if id_usuario:
        alvo = query_one("SELECT id, id_perfil FROM usuario WHERE id = ? AND D_E_L_E_T = 0", (id_usuario,))
        if alvo is None:
            abort(404)
        if alvo["id_perfil"] != perfil and (id_usuario == current_user.id or id_usuario == ADMIN_BLINDADO):
            flash("O perfil do administrador principal e o seu próprio não mudam por aqui.", "erro")
            return redirect(url_for("admin.usuarios"))
        db.execute("UPDATE usuario SET nome = ?, email = ?, id_perfil = ? WHERE id = ?",
                   (dados.nome, dados.email, perfil, id_usuario))
        db.commit()
        log_acesso("USUARIO_EDITADO", current_user.id, f"usuario={id_usuario} perfil={perfil}")
        flash(f"Usuário {dados.nome} salvo.", "sucesso")
        return redirect(url_for("admin.usuarios"))

    senha = _senha_sorteada()
    cur = db.execute(
        """INSERT INTO usuario (nome, email, senha_hash, id_perfil, ativo, precisa_trocar_senha)
           VALUES (?, ?, ?, ?, 1, 1)""", (dados.nome, dados.email, _hash(senha), perfil))
    db.commit()
    log_acesso("USUARIO_CRIADO", current_user.id, f"usuario={cur.lastrowid} perfil={perfil}")
    return _tela_usuarios(senha_nova={"nome": dados.nome, "email": dados.email, "senha": senha, "nova": True})


def _alvo_editavel(id_usuario: int):
    if not current_user.pode("auth", "editar"):
        abort(403)
    alvo = query_one("SELECT id, nome, email, ativo FROM usuario WHERE id = ? AND D_E_L_E_T = 0", (id_usuario,))
    if alvo is None:
        abort(404)
    return alvo


@admin_bp.route("/usuarios/<int:id_usuario>/ativo", methods=["POST"])
@login_required
def usuario_ativo(id_usuario: int):
    alvo = _alvo_editavel(id_usuario)
    if id_usuario in (current_user.id, ADMIN_BLINDADO):
        flash("Você não pode desativar a si mesmo nem o administrador principal.", "erro")
        return redirect(url_for("admin.usuarios"))
    novo = 0 if alvo["ativo"] else 1
    get_db().execute("UPDATE usuario SET ativo = ? WHERE id = ?", (novo, id_usuario))
    get_db().commit()
    log_acesso("USUARIO_ATIVADO" if novo else "USUARIO_DESATIVADO", current_user.id, f"usuario={id_usuario}")
    flash(f"{alvo['nome']} {'pode entrar de novo' if novo else 'não entra mais (os registros dele ficam)'}.", "sucesso")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:id_usuario>/senha", methods=["POST"])
@login_required
def usuario_senha(id_usuario: int):
    alvo = _alvo_editavel(id_usuario)
    if id_usuario == current_user.id:
        flash("Pra trocar a sua senha, use Trocar senha no seu nome, no rodapé do menu.", "erro")
        return redirect(url_for("admin.usuarios"))
    senha = _senha_sorteada()
    get_db().execute("UPDATE usuario SET senha_hash = ?, precisa_trocar_senha = 1 WHERE id = ?",
                     (_hash(senha), id_usuario))
    get_db().commit()
    log_acesso("SENHA_REDEFINIDA", current_user.id, f"usuario={id_usuario}")   # nunca a senha
    return _tela_usuarios(senha_nova={"nome": alvo["nome"], "email": alvo["email"], "senha": senha, "nova": False})


# ──────────────────────────────────────────────────────────────────────────────
# Segurança (parâmetros editáveis sem redeploy). Os valores vivem na tabela
# configuracao e já são lidos a cada request (core/auth._param_int,
# core/security.timeout_sessao_min, init_controle_ip): mudar aqui vale na hora.
# ──────────────────────────────────────────────────────────────────────────────

from modules.validacao_seguranca import MODOS_IP, SegurancaIn  # noqa: E402

_PARAMS_SEG = ("session_timeout_min", "max_login_tentativas", "lockout_janela_min", "ip_protecao_modo")
_PADRAO_SEG = {"session_timeout_min": "60", "max_login_tentativas": "5",
               "lockout_janela_min": "15", "ip_protecao_modo": "off"}


def _valores_seg() -> dict:
    linhas = query("SELECT chave, valor FROM configuracao WHERE chave IN (%s) AND D_E_L_E_T = 0"
                   % ",".join("?" * len(_PARAMS_SEG)), _PARAMS_SEG)
    atual = {r["chave"]: r["valor"] for r in linhas}
    return {k: (atual.get(k) if atual.get(k) is not None else _PADRAO_SEG[k]) for k in _PARAMS_SEG}


@admin_bp.route("/seguranca")
@login_required
def seguranca():
    if not current_user.pode("seguranca", "ver"):
        abort(403)
    return render_template("admin/seguranca.html", valores=_valores_seg(),
                           modos=[{"valor": k, "rotulo": v} for k, v in MODOS_IP.items()],
                           erros={}, pode_editar=current_user.pode("seguranca", "editar"))


@admin_bp.route("/seguranca/salvar", methods=["POST"])
@login_required
def seguranca_salvar():
    if not current_user.pode("seguranca", "editar"):
        abort(403)
    valores = {k: (request.form.get(k) or "").strip() for k in _PARAMS_SEG}
    try:
        dados = SegurancaIn(**valores)
    except Exception as exc:
        erros = {str((e.get("loc") or ["seguranca"])[0]): str(e.get("msg", "")).replace("Value error, ", "")
                 for e in (exc.errors() if hasattr(exc, "errors") else [{"loc": ["seguranca"], "msg": str(exc)}])}
        return render_template("admin/seguranca.html", valores={**_valores_seg(), **valores},
                               modos=[{"valor": k, "rotulo": v} for k, v in MODOS_IP.items()],
                               erros=erros, pode_editar=True), 422
    db = get_db()
    for chave in _PARAMS_SEG:
        db.execute("UPDATE configuracao SET valor = ? WHERE chave = ?", (getattr(dados, chave), chave))
        if db.execute("SELECT changes()").fetchone()[0] == 0:   # parâmetro ainda não semeado
            db.execute("INSERT INTO configuracao (chave, valor) VALUES (?, ?)", (chave, getattr(dados, chave)))
    db.commit()
    log_acesso("SEGURANCA_ALTERADA", current_user.id,
               f"timeout={dados.session_timeout_min} tent={dados.max_login_tentativas} "
               f"janela={dados.lockout_janela_min} ip={dados.ip_protecao_modo}")
    flash("Parâmetros de segurança salvos. Já valem no próximo acesso.", "sucesso")
    return redirect(url_for("admin.seguranca"))
