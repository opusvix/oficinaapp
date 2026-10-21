"""Prova do bloco de segurança: mass assignment (extra="forbid" e status inicial).

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_seguranca_validacao.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sys
import tempfile

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pydantic import ValidationError  # noqa: E402

from app import create_app  # noqa: E402
from modules.validacao_clientes import ClienteIn  # noqa: E402
from modules.validacao_os import ItemOSIn, OSIn  # noqa: E402
from modules.validacao_peca import PecaIn  # noqa: E402

falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def recusa(modelo, dados):
    try:
        modelo(**dados)
        return False
    except ValidationError as e:
        return any(err["type"] == "extra_forbidden" for err in e.errors())


# ── Modelo recusa campo que não declarou ─────────────────────────────────────
BASE = {
    ClienteIn: {"razao_social": "Bar do Zé"},
    PecaIn: {"codigo": "RES-01", "descricao": "Resistência"},
    OSIn: {"descricao_inicial": "forno não esquenta"},
    ItemOSIn: {"descricao": "Fio de silicone"},
}
for modelo, dados in BASE.items():
    try:
        modelo(**dados)
        ok = True
    except ValidationError as e:
        ok = str(e)
    chk(f"{modelo.__name__} aceita os campos dele (prova positiva)", ok is True, ok)
    for intruso in ("id_perfil", "D_E_L_E_T", "is_admin"):
        chk(f"{modelo.__name__} recusa campo intruso '{intruso}'", recusa(modelo, {**dados, intruso: "1"}))

# ── Status inicial: só aberta ou avaliação ───────────────────────────────────
for st in ("aprovada", "em_andamento", "entregue", "recusada"):
    try:
        OSIn(descricao_inicial="forno", status=st)
        chk(f"OSIn recusa status inicial '{st}'", False, "aceitou")
    except ValidationError:
        chk(f"OSIn recusa status inicial '{st}'", True)
chk("OSIn aceita 'avaliacao' (prova positiva)", OSIn(descricao_inicial="forno", status="avaliacao").status == "avaliacao")

# ── Pela rota: POST forjado não abre OS já entregue ──────────────────────────
app = create_app()
with app.app_context():
    from core.db import get_db
    db = get_db()
    db.execute("UPDATE usuario SET precisa_trocar_senha = 0")
    cli = db.execute("INSERT INTO cliente (razao_social) VALUES ('Bar') RETURNING id").fetchone()[0]
    db.commit()

c = app.test_client()
c.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
tk = re.search(rb'name="csrf-token" content="([^"]+)"', c.get("/os/nova").data).group(1).decode()


def contar():
    with app.app_context():
        from core.db import query_one
        return query_one("SELECT COUNT(*) AS n FROM ordem_servico")["n"]


antes = contar()
r = c.post("/os/nova", data={"id_cliente": str(cli), "descricao_inicial": "forno não esquenta",
                             "status": "entregue", "csrf_token": tk})
chk("POST com status=entregue -> 422 e nenhuma OS criada", r.status_code == 422 and contar() == antes,
    f"{r.status_code} OS {antes}->{contar()}")

r = c.post("/os/nova", data={"id_cliente": str(cli), "descricao_inicial": "forno não esquenta",
                             "status": "avaliacao", "foto_antes": "uploads/../../app.py",
                             "os_token": "token-forjado", "csrf_token": tk})
with app.app_context():
    from core.db import query_one
    nova = query_one("SELECT status, foto_antes, os_token FROM ordem_servico ORDER BY id DESC LIMIT 1")
chk("POST com campos extras: OS criada (prova positiva)", r.status_code == 302 and contar() == antes + 1,
    r.status_code)
chk("campos fora da whitelist não chegam ao banco",
    nova["status"] == "avaliacao" and nova["foto_antes"] is None and nova["os_token"] is None, dict(nova))

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
