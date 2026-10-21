"""Prova do bloco de segurança: headers, CSP com nonce e proteção das rotas.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_seguranca_headers.py
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
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402

app = create_app()
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


with app.app_context():
    from core.db import get_db
    db = get_db()
    db.execute("UPDATE usuario SET precisa_trocar_senha = 0")
    h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
    db.execute("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
               "VALUES ('Tec', 'tec@teste.local', ?, 2, 0)", (h,))
    cli = db.execute("INSERT INTO cliente (razao_social) VALUES ('Bar') RETURNING id").fetchone()[0]
    peca = db.execute("INSERT INTO peca (codigo, descricao) VALUES ('P1', 'Resistência') RETURNING id").fetchone()[0]
    id_os = db.execute("INSERT INTO ordem_servico (id_cliente, patrimonio) VALUES (?, 'X1') RETURNING id",
                       (cli,)).fetchone()[0]
    db.commit()

PAGINAS = ["/home", "/clientes/", f"/clientes/{cli}", "/estoque/", f"/estoque/{peca}",
           "/os/?periodo=todos", f"/os/{id_os}", "/os/nova", "/admin/perfis", "/admin/perfis/2/permissoes"]

# ── Anônimo não passa em nenhuma rota interna ────────────────────────────────
anon = app.test_client()
for url in PAGINAS + ["/notificacoes/", "/auth/trocar-senha", "/api/preferencia/x"]:
    r = anon.get(url)
    chk(f"anônimo em {url} -> login", r.status_code in (302, 401) and "login" in (r.headers.get("Location") or "login"),
        f"{r.status_code} {r.headers.get('Location')}")

adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})

# ── Headers ──────────────────────────────────────────────────────────────────
r = adm.get("/home")
csp = r.headers.get("Content-Security-Policy", "")
chk("Permissions-Policy presente", r.headers.get("Permissions-Policy") ==
    "geolocation=(), microphone=(), camera=()", r.headers.get("Permissions-Policy"))
script_src = next((p.strip() for p in csp.split(";") if p.strip().startswith("script-src")), "")
chk("script-src SEM 'unsafe-inline'", script_src and "unsafe-inline" not in script_src, script_src)
chk("script-src com nonce", "'nonce-" in script_src, script_src)
for h_ in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
    chk(f"{h_} presente", bool(r.headers.get(h_)))
chk("CSP fecha object-src e frame-ancestors", "object-src 'none'" in csp and "frame-ancestors 'none'" in csp, csp)

nonce1 = re.search(r"'nonce-([^']+)'", csp).group(1)
nonce2 = re.search(r"'nonce-([^']+)'", adm.get("/home").headers["Content-Security-Policy"]).group(1)
chk("nonce muda a cada request", nonce1 != nonce2)

# ── Toda página: script inline só com o nonce certo, zero on*= ───────────────
for url in PAGINAS:
    r = adm.get(url)
    html = r.data.decode("utf-8", "replace")
    nonce = re.search(r"'nonce-([^']+)'", r.headers.get("Content-Security-Policy", ""))
    nonce = nonce.group(1) if nonce else "?"
    inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
    sem = [a for a in inline if f'nonce="{nonce}"' not in a]
    chk(f"{url}: {len(inline)} script inline, todos com o nonce do request", r.status_code == 200 and not sem,
        f"{r.status_code} sem nonce: {sem[:2]}")
    handlers = re.findall(r"\son[a-z]+\s*=\s*[\"']", html)
    chk(f"{url}: nenhum handler on*= no HTML", not handlers, handlers[:3])

# ── Permissão vertical: técnico fora do admin ────────────────────────────────
tec = app.test_client()
tec.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
chk("técnico em /admin/perfis -> 403", tec.get("/admin/perfis").status_code == 403)
chk("técnico vê clientes (prova positiva)", tec.get("/clientes/").status_code == 200)
tk = re.search(rb'name="csrf-token" content="([^"]+)"', tec.get("/clientes/").data).group(1).decode()
r = tec.post("/clientes/salvar", data={"razao_social": "Hack", "csrf_token": tk})
chk("técnico não cria cliente (só VER) -> 403", r.status_code == 403, r.status_code)

# ── Página de erro amigável (título e ícone no lugar certo) ─────────────────
r = anon.get("/rota-que-nao-existe")
html = r.data.decode()
chk("404 mostra o título 'Página não encontrada'", r.status_code == 404 and "Página não encontrada" in html)
chk("404 não mostra nome de ícone como texto", re.search(r">\s*ph-map-pin\s*<", html) is None)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
