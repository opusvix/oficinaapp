"""Auth: login, sessão, perfis, permissões, força bruta."""
from __future__ import annotations

import os
import secrets
import sqlite3
import string
import time
from typing import Optional

import bcrypt
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from core.auditoria import log_acesso
from core.db import get_db, query_one

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()


# ──────────────────────────────────────────────────────────────────────────────
# Modelo de usuário
# ──────────────────────────────────────────────────────────────────────────────

class User(UserMixin):
    """Usuário do sistema."""

    def __init__(
        self,
        id: int,
        nome: str,
        email: str,
        senha_hash: str,
        id_perfil: int,
        perfil_nome: str,
        ativo: bool = True,
        precisa_trocar_senha: bool = False,
    ):
        self.id = id
        self.nome = nome
        self.email = email
        self.senha_hash = senha_hash
        self.id_perfil = id_perfil
        self.perfil_nome = perfil_nome
        self.ativo = ativo
        self.precisa_trocar_senha = precisa_trocar_senha
        self._perms = None

    @property
    def is_active(self) -> bool:
        return self.ativo

    @property
    def permissoes(self) -> dict:
        """Cache de permissões: {chave_modulo: {'ver': 1, 'editar': 1}}."""
        if self._perms is None:
            rows = get_db().execute(
                """SELECT m.chave, p.pode_ver, p.pode_editar
                   FROM permissoes p
                   JOIN modulo m ON m.id = p.id_modulo
                   WHERE p.id_perfil = ? AND p.D_E_L_E_T = 0 AND m.D_E_L_E_T = 0""",
                (self.id_perfil,),
            ).fetchall()
            self._perms = {r["chave"]: {"ver": r["pode_ver"], "editar": r["pode_editar"]} for r in rows}
        return self._perms

    def pode(self, chave_modulo: str, acao: str = "ver") -> bool:
        """Verifica permissão VER/EDITAR para um módulo."""
        p = self.permissoes.get(chave_modulo)
        return bool(p and p.get(acao, 0)) if p else False


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    row = query_one(
        """SELECT u.id, u.nome, u.email, u.senha_hash, u.id_perfil, u.ativo,
                  u.precisa_trocar_senha, p.nome as perfil_nome
           FROM usuario u
           JOIN perfil p ON p.id = u.id_perfil
           WHERE u.id = ? AND u.D_E_L_E_T = 0 AND u.ativo = 1""",
        (int(user_id),),
    )
    # ativo = 1 AQUI, e não só no login: o Flask-Login só olha is_active ao entrar,
    # então usuário desativado com sessão aberta seguia usando o sistema.
    if row:
        return User(
            id=row["id"],
            nome=row["nome"],
            email=row["email"],
            senha_hash=row["senha_hash"],
            id_perfil=row["id_perfil"],
            perfil_nome=row["perfil_nome"],
            ativo=bool(row["ativo"]),
            precisa_trocar_senha=bool(row["precisa_trocar_senha"]),
        )
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Força bruta (Forca_Bruta_Login): falhas por e-mail OU por IP, NO BANCO
# (em session o atacante zera a conta apagando o cookie)
# ──────────────────────────────────────────────────────────────────────────────

MAX_TENTATIVAS = 5      # padrão; o valor vivo está em configuracao.max_login_tentativas
JANELA_MINUTOS = 15     # padrão; o valor vivo está em configuracao.lockout_janela_min
IGNORAR_EMAILS = set(
    e.strip().lower()
    for e in os.getenv("EMAIL_IGNORAR_BLOQUEIOS", "").split(",")
    if e.strip()
)
MSG_CREDENCIAIS = "Credenciais inválidas."
# Hash de uma senha qualquer: e-mail inexistente também paga um bcrypt, senão
# o tempo de resposta denuncia quais e-mails existem.
_HASH_FALSO = bcrypt.hashpw(b"nao-existe", bcrypt.gensalt()).decode()


def _param_int(chave: str, padrao: int) -> int:
    row = query_one(
        "SELECT valor FROM configuracao WHERE chave = ? AND D_E_L_E_T = 0", (chave,)
    )
    try:
        return int(row["valor"]) if row else padrao
    except (TypeError, ValueError):
        return padrao


def registrar_tentativa(email: str, ip: str, sucesso: bool) -> None:
    """Toda tentativa vira linha, sucesso ou falha."""
    db = get_db()
    db.execute(
        "INSERT INTO login_tentativas (email, ip, sucesso, quando) VALUES (?, ?, ?, ?)",
        (email.lower()[:150], ip, 1 if sucesso else 0, int(time.time())),
    )
    db.commit()


def falhas_recentes(email: str, ip: str) -> int:
    """Falhas na janela contadas por IP OU por e-mail.

    Pelo e-mail, só contam as falhas depois do último login certo daquele
    e-mail (quem errou 4 vezes e acertou não fica a 1 erro do bloqueio). Pelo
    IP, contam todas: acertar a senha de uma conta não zera o IP do atacante.
    """
    desde = int(time.time()) - _param_int("lockout_janela_min", JANELA_MINUTOS) * 60
    row = query_one(
        """SELECT COUNT(*) AS n FROM login_tentativas t
            WHERE t.sucesso = 0 AND t.quando > ?
              AND (t.ip = ?
                   OR (t.email = ? AND t.quando > COALESCE(
                         (SELECT MAX(s.quando) FROM login_tentativas s
                           WHERE s.email = ? AND s.sucesso = 1), 0)))""",
        (desde, ip, email.lower(), email.lower()),
    )
    return int(row["n"]) if row else 0


def esta_bloqueado(email: str, ip: str) -> bool:
    if falhas_recentes(email, ip) < _param_int("max_login_tentativas", MAX_TENTATIVAS):
        return False
    if email.lower() in IGNORAR_EMAILS:
        # Isenção (Admin_Inicial_Padrao): pula a tranca, mas TODO uso fica na auditoria
        log_acesso("LOGIN_ISENCAO_LOCKOUT", detalhe=f"email={email.lower()}")
        return False
    log_acesso("LOGIN_BLOQUEADO", detalhe=f"email={email.lower()}")
    return True


def limpar_tentativas(email: str, ip: str) -> None:
    """Apaga as tentativas de um e-mail ou IP (uso de teste e de suporte)."""
    db = get_db()
    db.execute(
        "DELETE FROM login_tentativas WHERE email = ? OR ip = ?", (email.lower(), ip)
    )
    db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap do admin inicial (via variáveis de ambiente)
# ──────────────────────────────────────────────────────────────────────────────

def bootstrap_admin() -> None:
    """Cria/atualiza admin inicial a partir de ADMIN_EMAIL / ADMIN_SENHA_INICIAL / ADMIN_RESET_SENHA."""
    resetar = os.getenv("ADMIN_RESET_SENHA", "").lower() in ("1", "true", "sim", "yes")
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if not email:
        return

    db = get_db()
    row = query_one("SELECT id FROM usuario WHERE email = ? AND D_E_L_E_T = 0", (email,))
    existe = row is not None

    if existe and not resetar:
        return  # idempotente

    senha_env = os.getenv("ADMIN_SENHA_INICIAL", "").strip()
    if senha_env:
        senha = senha_env
    else:
        # Sorteia 20 chars sem caracteres ambíguos
        alfabeto = (string.ascii_letters + string.digits).translate(
            str.maketrans("", "", "0O1lI")
        )
        senha = "".join(secrets.choice(alfabeto) for _ in range(20))
        print(f"[BOOT] SENHA INICIAL SORTEADA: {senha}")  # única aparição no log

    hash_senha = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()

    if existe:
        # Atualiza senha e garante perfil admin + ativo
        db.execute(
            """UPDATE usuario
                  SET senha_hash = ?, id_perfil = 1, ativo = 1,
                      precisa_trocar_senha = 1, id_cliente = NULL, ve_todos_clientes = 1
                WHERE email = ?""",
            (hash_senha, email),
        )
        print(f"[BOOT] ADMIN_RESET_SENHA ligada: senha de {email} REDEFINIDA.")
        print("[BOOT] APAGUE a variável ADMIN_RESET_SENHA do painel agora.")
    else:
        # Insere novo admin (tenta id=1 para blindagem contra exclusão)
        try:
            db.execute(
                """INSERT INTO usuario (id, nome, email, senha_hash, id_perfil, ativo, precisa_trocar_senha)
                     VALUES (1, 'Administrador', ?, ?, 1, 1, 1)""",
                (email, hash_senha),
            )
        except sqlite3.IntegrityError:
            # id=1 ocupado, insere sem id fixo
            db.execute(
                """INSERT INTO usuario (nome, email, senha_hash, id_perfil, ativo, precisa_trocar_senha)
                     VALUES ('Administrador', ?, ?, 1, 1, 1)""",
                (email, hash_senha),
            )
        # Ajusta sequence se SQLite
        db.execute("UPDATE sqlite_sequence SET seq = MAX(seq, 1) WHERE name = 'usuario'")
        print(f"[BOOT] Admin inicial criado: {email}")

    db.commit()


def aplicar_auto_liberacoes() -> None:
    """Módulo NOVO num grupo auto-liberado já nasce permitido (Auto_Liberacao_por_Grupo).

    Roda no boot, DEPOIS do init_db/bootstrap_admin. Só CRIA linha de permissão
    pra módulo que ainda NÃO tem nenhuma (inclusive a linha 0/0 do UPSERT da matriz),
    então respeita toda decisão manual: nunca reabre o que o admin fechou de propósito.
    """
    db = get_db()
    regras = db.execute(
        "SELECT id_perfil, grupo, auto_ver, auto_editar FROM perfis_grupos_auto "
        "WHERE D_E_L_E_T = 0 AND (auto_ver = 1 OR auto_editar = 1)"
    ).fetchall()
    criadas = 0
    for r in regras:
        mods = db.execute(
            "SELECT id FROM modulo WHERE COALESCE(grupo, 'Outros') = ? AND D_E_L_E_T = 0",
            (r["grupo"],),
        ).fetchall()
        for m in mods:
            if db.execute(
                "SELECT 1 FROM permissoes WHERE id_perfil = ? AND id_modulo = ?",
                (r["id_perfil"], m["id"]),
            ).fetchone():
                continue
            editar = 1 if r["auto_editar"] else 0
            ver = 1 if (r["auto_ver"] or editar) else 0   # EDITAR implica VER
            db.execute(
                "INSERT INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar) VALUES (?, ?, ?, ?)",
                (r["id_perfil"], m["id"], ver, editar),
            )
            criadas += 1
    if criadas:
        db.commit()
        print(f"[BOOT] Auto-liberação: {criadas} permissão(ões) de módulo novo criada(s).")


# ──────────────────────────────────────────────────────────────────────────────
# Rotas de login / logout / troca de senha
# ──────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        ip = request.remote_addr or "0.0.0.0"

        if esta_bloqueado(email, ip):
            flash("Muitas tentativas. Aguarde alguns minutos.", "erro")
            return render_login(email=email)

        user_row = query_one(
            """SELECT u.id, u.nome, u.email, u.senha_hash, u.id_perfil, u.ativo,
                      u.precisa_trocar_senha, p.nome as perfil_nome
               FROM usuario u
               JOIN perfil p ON p.id = u.id_perfil
               WHERE u.email = ? AND u.D_E_L_E_T = 0""",
            (email,),
        )

        hash_conferido = user_row["senha_hash"] if user_row else _HASH_FALSO
        senha_ok = bcrypt.checkpw(senha.encode(), hash_conferido.encode()) and user_row is not None

        # Inativo com senha certa recebe a MESMA mensagem: "Usuário inativo" só
        # aparecia com a senha correta, e confirmava a senha pra quem tentava.
        if not senha_ok or not user_row["ativo"]:
            registrar_tentativa(email, ip, sucesso=False)
            motivo = "inativo" if senha_ok else "senha"
            log_acesso("LOGIN_FALHA", user_row["id"] if user_row else None,
                       f"email={email} motivo={motivo}")
            flash(MSG_CREDENCIAIS, "erro")
            return render_login(email=email)

        user = User(
            id=user_row["id"],
            nome=user_row["nome"],
            email=user_row["email"],
            senha_hash=user_row["senha_hash"],
            id_perfil=user_row["id_perfil"],
            perfil_nome=user_row["perfil_nome"],
            ativo=bool(user_row["ativo"]),
            precisa_trocar_senha=bool(user_row["precisa_trocar_senha"]),
        )
        login_user(user)
        # Sessão com vida de PERMANENT_SESSION_LIFETIME; a inatividade
        # é contada a partir daqui (security.init_timeout_sessao)
        session.permanent = True
        session["ultima_atividade"] = int(time.time())
        registrar_tentativa(email, ip, sucesso=True)
        log_acesso("LOGIN", user.id, f"email={email}")

        if user.precisa_trocar_senha:
            return redirect(url_for("auth.trocar_senha"))

        return redirect(url_for("home"))

    if request.args.get("expirado"):
        flash("Sua sessão expirou por inatividade. Entre de novo.", "erro")
    return render_login()


def render_login(email: str = ""):
    """Tela de login (templates/login.html)."""
    return render_template("login.html", email=email)


@auth_bp.route("/logout")
@login_required
def logout():
    log_acesso("LOGOUT", current_user.id)
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/trocar-senha", methods=["GET", "POST"])
@login_required
def trocar_senha():
    from core.demo import modo_demo
    if modo_demo():
        # Demo compartilhada: a senha é pública de propósito. Trocar trancaria os outros.
        flash("Na demonstração não é possível trocar a senha.", "erro")
        return redirect(url_for("home"))
    if request.method == "POST":
        atual = request.form.get("senha_atual") or ""
        nova = request.form.get("senha_nova") or ""
        confirma = request.form.get("senha_confirma") or ""

        if not bcrypt.checkpw(atual.encode(), current_user.senha_hash.encode()):
            flash("Senha atual incorreta.", "erro")
        elif len(nova) < 8:
            flash("Nova senha deve ter pelo menos 8 caracteres.", "erro")
        elif nova != confirma:
            flash("Confirmação não confere.", "erro")
        elif nova == atual:
            # senha provisória é conhecida por quem a gerou: repetir anula a troca
            flash("A nova senha precisa ser diferente da atual.", "erro")
        else:
            hash_nova = bcrypt.hashpw(nova.encode(), bcrypt.gensalt()).decode()
            get_db().execute(
                "UPDATE usuario SET senha_hash = ?, precisa_trocar_senha = 0 WHERE id = ?",
                (hash_nova, current_user.id),
            )
            get_db().commit()
            current_user.senha_hash = hash_nova
            current_user.precisa_trocar_senha = False
            log_acesso("TROCA_SENHA", current_user.id)
            flash("Senha alterada com sucesso.", "sucesso")
            return redirect(url_for("home"))

    return render_template("trocar_senha.html", forcar=current_user.precisa_trocar_senha)