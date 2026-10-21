"""Prova do bloco de segurança: IDOR na OS e IP real atrás do proxy.

Roda num banco DESCARTÁVEL (arquivo temporário), nunca no instance/oficina.db.
    python scripts/teste_seguranca_os_ip.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="oficina_teste_")
os.environ["FLASK_DATABASE"] = os.path.join(_tmp, "teste.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402

app = create_app()
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


SENHA_TEC = "SenhaTecnico2026"
with app.app_context():
    from core.db import get_db
    db = get_db()
    h = bcrypt.hashpw(SENHA_TEC.encode(), bcrypt.gensalt()).decode()
    db.execute("UPDATE usuario SET precisa_trocar_senha = 0 WHERE email = ?", ("admin@teste.local",))
    tec_a = db.execute(
        "INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
        "VALUES ('Tec A', 'a@teste.local', ?, 2, 0)", (h,)).lastrowid
    tec_b = db.execute(
        "INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
        "VALUES ('Tec B', 'b@teste.local', ?, 2, 0)", (h,)).lastrowid
    cli = db.execute("INSERT INTO cliente (razao_social) VALUES ('Lanchonete Teste')").lastrowid
    os_a = db.execute(
        "INSERT INTO ordem_servico (id_cliente, id_tecnico, patrimonio, status) "
        "VALUES (?, ?, 'PAT-DO-A', 'aprovada')", (cli, tec_a)).lastrowid
    os_b = db.execute(
        "INSERT INTO ordem_servico (id_cliente, id_tecnico, patrimonio, status) "
        "VALUES (?, ?, 'PAT-DO-B', 'aprovada')", (cli, tec_b)).lastrowid
    db.commit()


def entrar(c, email, senha):
    return c.post("/auth/login", data={"email": email, "senha": senha})


def csrf(c, url):
    r = c.get(url)
    m = (re.search(rb'name="csrf-token" content="([^"]+)"', r.data)
         or re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data))
    return m.group(1).decode() if m else ""


# ── IDOR: técnico A contra a OS do técnico B ─────────────────────────────────
c = app.test_client()
r = entrar(c, "a@teste.local", SENHA_TEC)
chk("login técnico A", r.status_code == 302, r.status_code)
tk = csrf(c, f"/os/{os_a}")

r = c.get("/os/?periodo=todos")
chk("listagem do A mostra a OS dele", b"PAT-DO-A" in r.data)
chk("listagem do A NÃO mostra a OS do B", b"PAT-DO-B" not in r.data)

chk("A abre a própria OS (prova positiva)", c.get(f"/os/{os_a}").status_code == 200)
chk("A abre OS do B -> 404", c.get(f"/os/{os_b}").status_code == 404)
chk("A abre OS inexistente -> 404 (mesma resposta)", c.get("/os/999999").status_code == 404)

for acao, dados in (
    ("execucao", {"descricao_execucao": "troquei a resistencia", "testado_funcionamento": "1"}),
    ("entregar", {}),
    ("item", {"descricao": "Fio", "quantidade": "1", "preco_unitario": "1"}),
    ("token", {}),
    ("foto", {"momento": "depois"}),
):
    r = c.post(f"/os/{os_b}/{acao}", data={**dados, "csrf_token": tk})
    chk(f"A faz POST /{acao} na OS do B -> 404", r.status_code == 404, r.status_code)

r = c.post(f"/os/{os_a}/token", data={"csrf_token": tk})
chk("A gera link na própria OS (prova positiva)", r.status_code == 302, r.status_code)

r = c.post("/os/nova", data={"id_cliente": str(cli), "id_tecnico": str(tec_b),
                             "descricao_inicial": "forno nao esquenta", "csrf_token": tk})
chk("A abre OS nova", r.status_code == 302, r.status_code)
with app.app_context():
    from core.db import query_one
    nova = query_one("SELECT id_tecnico FROM ordem_servico ORDER BY id DESC LIMIT 1")
chk("OS aberta pelo A fica com o A, mesmo pedindo o B", nova["id_tecnico"] == tec_a, dict(nova))

# ── Administrador continua vendo tudo ────────────────────────────────────────
adm = app.test_client()
chk("login admin", entrar(adm, "admin@teste.local", "SenhaTesteAdmin2026").status_code == 302)
r = adm.get("/os/?periodo=todos")
chk("admin vê OS do A e do B", b"PAT-DO-A" in r.data and b"PAT-DO-B" in r.data)
chk("admin abre OS do B", adm.get(f"/os/{os_b}").status_code == 200)

# ── IP real: o atacante injeta o 1º item do X-Forwarded-For ──────────────────
# Traefik ANEXA o IP real no fim. O atacante troca o começo a cada tentativa.
ip = app.test_client()
codigos = []
for n in range(11):
    r = ip.post("/auth/login",
                data={"email": f"x{n}@teste.local", "senha": "errada"},
                headers={"X-Forwarded-For": f"9.9.9.{n}, 5.5.5.5"})
    codigos.append(r.status_code)
chk("11ª tentativa do mesmo IP real cai no limite (429) mesmo trocando o XFF",
    codigos[-1] == 429, codigos)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
