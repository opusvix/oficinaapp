"""Menu da sidebar (por permissão) + contador de notificações.

O menu nasce da tabela `modulo` (seed) — não existe lista hardcoded no
template. Cadastrar um módulo já o coloca no menu, se o perfil tiver VER.

Item cuja rota ainda não existe no `url_map` sai desabilitado como
"Em breve": o menu acende sozinho quando a fase daquela rota entrar.
Nada de link morto apontando pra 404.
"""
from __future__ import annotations

from typing import Optional

from flask import current_app, g, request
from flask_login import current_user

from core.db import query, query_one


def get_user_menu(user) -> list[dict]:
    """Grupos do menu lateral, contendo só os módulos que o perfil pode VER.

    Ordem dos grupos = ordem de `id` no seed (admin 1, cadastros 11,
    operacional 21, financeiro 31, relatórios 41).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []

    permitidas = user.permissoes
    if not permitidas:
        return []

    try:
        rotas = {r.rule.rstrip("/") for r in current_app.url_map.iter_rules()}
    except Exception:  # sem app (fora de request): menu vazio em vez de 500
        return []

    grupos: dict[str, list[dict]] = {}
    ordem: list[str] = []

    linhas = query(
        """SELECT id, chave, nome, grupo, icone, rota, em_breve
             FROM modulo
            WHERE D_E_L_E_T = 0
            ORDER BY id"""
    )
    for ln in linhas:
        perm = permitidas.get(ln["chave"])
        if not perm or not perm.get("ver"):
            continue
        rota = (ln["rota"] or "").rstrip("/")
        pronto = bool(rota) and not ln["em_breve"] and rota in rotas
        chave_grupo = ln["grupo"] or "Outros"
        if chave_grupo not in grupos:
            grupos[chave_grupo] = []
            ordem.append(chave_grupo)
        grupos[chave_grupo].append(
            {
                "chave": ln["chave"],
                "nome": ln["nome"],
                "icone": ln["icone"] or "ph-squares-four",
                "rota": rota,
                "pronto": pronto,
                "ativo": pronto
                and (request.path == rota or request.path.startswith(rota + "/")),
            }
        )

    # Só UM item aceso: o de rota mais longa que casa com a página. Sem isso,
    # /financeiro/caixa acendia "Financeiro / PDV" (/financeiro) E "Controle de Caixa".
    acesos = [it for nome in ordem for it in grupos[nome] if it["ativo"]]
    if len(acesos) > 1:
        vencedor = max(acesos, key=lambda it: len(it["rota"]))
        for it in acesos:
            it["ativo"] = it is vencedor

    return [{"nome": nome, "itens": grupos[nome]} for nome in ordem]


# ──────────────────────────────────────────────────────────────────────────────
# Notificações (sino)
# ──────────────────────────────────────────────────────────────────────────────

def nao_lidas(user) -> int:
    """Quantas notificações não lidas o usuário tem (cache por request)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    if getattr(g, "_notif_nao_lidas", None) is None:
        row = query_one(
            """SELECT COUNT(*) AS n FROM notificacao
                WHERE id_usuario = ? AND lida = 0 AND D_E_L_E_T = 0""",
            (user.id,),
        )
        g._notif_nao_lidas = int(row["n"]) if row else 0
    return g._notif_nao_lidas


def invalidar_contador_notificacoes() -> None:
    """Zera o cache do contador (depois de marcar como lida/criar)."""
    if hasattr(g, "_notif_nao_lidas"):
        del g._notif_nao_lidas


def notificar(
    id_usuario: int,
    titulo: str,
    mensagem: str = "",
    tipo: str = "info",
    rota: str = "",
) -> None:
    """Cria uma notificação. Tipos: info | aviso | sucesso | erro."""
    from core.db import get_db

    get_db().execute(
        """INSERT INTO notificacao (id_usuario, tipo, titulo, mensagem, rota)
             VALUES (?, ?, ?, ?, ?)""",
        (id_usuario, tipo, titulo, mensagem, rota or None),
    )
    get_db().commit()
    invalidar_contador_notificacoes()


def init_menu(app) -> None:
    """Disponibiliza `user_menu` e `notif_nao_lidas` em todos os templates.

    Tudo em try/except: se o banco estiver fora, a página de erro ainda tem
    que renderizar — o menu não pode ser o que derruba o 500.
    """

    @app.context_processor
    def _injetar_menu():
        menu: list[dict] = []
        badge = 0
        user = current_user
        try:
            menu = get_user_menu(user)
            badge = nao_lidas(user)
        except Exception:
            current_app.logger.exception("MENU_FALHA usuario=%s", getattr(user, "id", None))
        return {"user_menu": menu, "notif_nao_lidas": badge}
