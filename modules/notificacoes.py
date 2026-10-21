"""Notificações do usuário (sino da topbar)."""
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from core.db import get_db, query
from core.menu import invalidar_contador_notificacoes

notificacoes_bp = Blueprint("notificacoes", __name__, url_prefix="/notificacoes")


@notificacoes_bp.route("/")
@login_required
def listar():
    itens = query(
        """SELECT id, tipo, titulo, mensagem, rota, lida, datestamp_insert
             FROM notificacao
            WHERE id_usuario = ? AND D_E_L_E_T = 0
            ORDER BY lida ASC, id DESC
            LIMIT 200""",
        (current_user.id,),
    )
    return render_template("notificacoes.html", itens=itens)


@notificacoes_bp.route("/marcar-lidas", methods=["POST"])
@login_required
def marcar_lidas():
    destino = request.form.get("destino") or url_for("notificacoes.listar")
    if not destino.startswith("/") or destino.startswith("//"):
        destino = url_for("notificacoes.listar")
    db = get_db()
    db.execute(
        "UPDATE notificacao SET lida = 1 WHERE id_usuario = ? AND lida = 0 AND D_E_L_E_T = 0",
        (current_user.id,),
    )
    db.commit()
    invalidar_contador_notificacoes()
    flash("Notificações marcadas como lidas.", "sucesso")
    return redirect(destino)
