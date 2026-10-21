"""Prova do bloco de segurança: SECRET_KEY, cookies de sessão e timeout.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_seguranca_sessao.py
Sai com código 1 se algum caso falhar.
"""
import os
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def ambiente(**extra):
    env = dict(os.environ)
    env["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
    env["ADMIN_EMAIL"] = "admin@teste.local"
    env["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
    env.pop("ADMIN_RESET_SENHA", None)
    env.update(extra)
    return env


def rodar(codigo, **extra):
    """Sobe o app num processo limpo (o .env não sobrescreve o que vier aqui)."""
    return subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=ambiente(**extra),
                          capture_output=True, text=True, timeout=120)


# ── SECRET_KEY: sem padrão no código ─────────────────────────────────────────
for rotulo, valor in (("vazia", ""), ("curta", "dev-change-me")):
    p = rodar("import app", SECRET_KEY=valor)
    chk(f"SECRET_KEY {rotulo}: app NÃO sobe", p.returncode != 0 and "SECRET_KEY" in p.stderr,
        p.stderr[-200:])
p = rodar("import app", SECRET_KEY="x" * 64)
chk("SECRET_KEY de 64: app sobe (prova positiva)", p.returncode == 0, p.stderr[-200:])

# ── Cookie no modo servidor (sem FLASK_ENV=development) ──────────────────────
COOKIE = (
    "import app\n"
    "c = app.app.test_client()\n"
    "r = c.post('/auth/login', data={'email':'admin@teste.local','senha':'SenhaTesteAdmin2026'})\n"
    "print('|'.join(r.headers.getlist('Set-Cookie')))\n"
)
p = rodar(COOKIE, FLASK_ENV="production", SECRET_KEY="y" * 64)
ck = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""   # última linha: o boot imprime antes
sessao = next((s for s in ck.split("|") if s.startswith("session=")), "")
chk("servidor: cookie de sessão foi emitido", bool(sessao), ck or p.stderr[-200:])
chk("servidor: cookie Secure", "Secure" in sessao, sessao)
chk("servidor: cookie HttpOnly", "HttpOnly" in sessao, sessao)
chk("servidor: cookie SameSite=Lax", "SameSite=Lax" in sessao, sessao)
chk("servidor: cookie com validade (sessão permanente, 7 dias)", "Expires=" in sessao, sessao)

p = rodar(COOKIE, FLASK_ENV="development", SECRET_KEY="y" * 64)
sessao_dev = next((s for s in (p.stdout.strip().splitlines() or [""])[-1].split("|") if s.startswith("session=")), "")
chk("dev local: cookie sem Secure (http://127.0.0.1 funciona)", sessao_dev and "Secure" not in sessao_dev,
    sessao_dev)

# ── Timeout por inatividade ──────────────────────────────────────────────────
os.environ.update({k: v for k, v in ambiente(FLASK_ENV="development").items()
                   if k in ("FLASK_DATABASE", "ADMIN_EMAIL", "ADMIN_SENHA_INICIAL", "FLASK_ENV")})
sys.path.insert(0, RAIZ)
from app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from core.db import get_db
    get_db().execute("UPDATE usuario SET precisa_trocar_senha = 0")
    get_db().commit()

c = app.test_client()
c.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
chk("ativo há pouco: /home abre (prova positiva)", c.get("/home").status_code == 200)

with c.session_transaction() as s:
    s["ultima_atividade"] = int(time.time()) - 61 * 60
r = c.get("/home")
chk("61 min parado: volta pro login com expirado=1",
    r.status_code == 302 and "expirado=1" in (r.headers.get("Location") or ""),
    f"{r.status_code} {r.headers.get('Location')}")
chk("depois de expirar a sessão morreu de fato", c.get("/home").status_code == 302)
r = c.get("/auth/login?expirado=1")
chk("tela de login avisa a expiração", "expirou por inatividade".encode() in r.data)

with app.app_context():
    get_db().execute("UPDATE configuracao SET valor = '0' WHERE chave = 'session_timeout_min'")
    get_db().commit()
c.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
with c.session_transaction() as s:
    s["ultima_atividade"] = int(time.time()) - 10 * 3600
chk("timeout 0 na configuracao: desligado", c.get("/home").status_code == 200)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
