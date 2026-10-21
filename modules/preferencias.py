"""Preferências de UI por usuário (Padrao_Tabela: prefs por usuário no banco).

A TabelaAvancada persiste colunas visíveis, linhas/página e ordenação via
GET/POST /api/preferencia/<chave>. Chave limitada a [A-Za-z0-9_.-]{1,80}:
entra na URL e vira coluna do banco, não fica à vontade.
"""
from __future__ import annotations

import json
import re

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from core.db import query_one, transaction

pref_bp = Blueprint("preferencias", __name__)

_CHAVE_OK = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@pref_bp.route("/api/preferencia/<chave>", methods=["GET", "POST"])
@login_required
def preferencia(chave: str):
    if not _CHAVE_OK.match(chave):
        return jsonify({"erro": "chave inválida"}), 400

    if request.method == "GET":
        linha = query_one(
            "SELECT valor FROM usuario_preferencias "
            " WHERE id_usuario = ? AND chave = ?",
            (current_user.id, chave),
        )
        try:
            return jsonify(json.loads(linha["valor"]) if linha and linha["valor"] else {})
        except (TypeError, ValueError):
            # JSON corrompido não derruba a tabela: volta ao padrão.
            return jsonify({})

    dados = request.get_json(silent=True) or {}
    ordena = dados.get("ordena")
    valor = {
        "porPagina": max(1, min(5000, int(dados.get("porPagina") or 50))),
        "ocultas": {str(k)[:60]: bool(v)
                    for k, v in (dados.get("ocultas") or {}).items()},
        "ordena": (
            {"col": str(ordena.get("col"))[:60],
             "dir": "desc" if str(ordena.get("dir")) == "desc" else "asc"}
            if isinstance(ordena, dict) and ordena.get("col") else None
        ),
    }
    with transaction() as db:
        db.execute(
            """INSERT INTO usuario_preferencias (id_usuario, chave, valor, atualizado_em)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id_usuario, chave)
               DO UPDATE SET valor = excluded.valor,
                             atualizado_em = CURRENT_TIMESTAMP""",
            (current_user.id, chave, json.dumps(valor, ensure_ascii=False)),
        )
    return jsonify({"ok": True})
