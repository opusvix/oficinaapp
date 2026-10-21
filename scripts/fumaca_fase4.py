"""Fumaça Fase 4: Clientes + Equipamentos (listagem, validação, soft delete).

Roda contra o app em memória (mesmo banco dev):
    .venv\\Scripts\\python.exe scripts\\fumaca_fase4.py
"""
import re
import sys

sys.path.insert(0, ".")
from app import create_app  # noqa: E402

app = create_app()
c = app.test_client()

falhas = []


def chk(rotulo, cond, detalhe=""):
    if cond:
        print(f"OK   {rotulo}")
    else:
        print(f"FAIL {rotulo}  <- {detalhe}")
        falhas.append(rotulo)


def token(url="/clientes/"):
    """CSRF da sessão atual. Com sessão ativa /auth/login redireciona (sem
    meta no corpo), então o default é a página autenticada."""
    r = c.get(url)
    m = (re.search(rb'name="csrf-token" content="([^"]+)"', r.data)
         or re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data))
    return m.group(1).decode() if m else ""


def login(email, senha):
    return c.post("/auth/login", data={"email": email, "senha": senha,
                                       "csrf_token": token("/auth/login")},
                  follow_redirects=False)


def logout():
    c.get("/auth/logout", follow_redirects=False)


import os  # noqa: E402

EMAIL_ADMIN = os.getenv("ADMIN_EMAIL", "admin@oficina.local")
SENHA_ADMIN = os.getenv("ADMIN_SENHA", "OficinaDev2026!")

# ──────────────────────────────────────────────────────────────────────────────
# 1. Rotas, menu e estáticos
# ──────────────────────────────────────────────────────────────────────────────

r = c.get("/clientes/")
chk("/clientes/ anon -> login",
    r.status_code == 302 and "/auth/login" in (r.headers.get("Location") or ""),
    str(r.headers.get("Location")))

r = login(EMAIL_ADMIN, SENHA_ADMIN)
chk("login admin", r.status_code == 302, str(r.status_code))

r = c.get("/clientes/")
chk("/clientes/ admin 200", r.status_code == 200, str(r.status_code))
chk("listagem usa TabelaAvancada", b"data-tabela" in r.data and b'data-pref-key="clientes"' in r.data)
chk("listagem tem botao novo cliente", b"Novo cliente" in r.data)
chk("listagem sem traceback", b"Traceback" not in r.data)

r = c.get("/home")
chk("menu acendeu /clientes/ (rota existe)",
    b'href="/clientes"' in r.data or b'href="/clientes/"' in r.data)
chk("menu sem hex da marca", b"#3387E9" not in r.data)

r = c.get("/static/js/tabela-avancada.js")
chk("tabela-avancada.js servido", r.status_code == 200 and len(r.data) > 10000,
    f"{r.status_code} {len(r.data)}B")

# ──────────────────────────────────────────────────────────────────────────────
# 2. Perfil técnico: vê, não edita
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import get_db, query_one
    from flask_bcrypt import Bcrypt

    if not query_one("SELECT id FROM usuario WHERE email = ? AND D_E_L_E_T = 0",
                     ("tecnico.teste@oficina.local",)):
        senha_hash = Bcrypt(app).generate_password_hash("TecnicoTeste2026!").decode()
        db = get_db()
        db.execute("INSERT INTO usuario (nome, email, senha_hash, id_perfil) "
                   "VALUES (?, ?, ?, 2)",
                   ("Técnico de Teste", "tecnico.teste@oficina.local", senha_hash))
        db.commit()

logout()
r = login("tecnico.teste@oficina.local", "TecnicoTeste2026!")
chk("login tecnico", r.status_code == 302, str(r.status_code))

r = c.get("/clientes/")
chk("tecnico vê listagem (VER)", r.status_code == 200, str(r.status_code))
chk("tecnico sem botao novo cliente (nem modal)", b"novoCliente()" not in r.data)
chk("tecnico vê slot esmaecido com tooltip específico",
    "apenas para o perfil Administrador" in r.data.decode("utf-8", "ignore"))

r = c.post("/clientes/salvar", data={"razao_social": "Hacker Ltda",
                                     "csrf_token": token()},
           follow_redirects=False)
chk("tecnico POST salvar -> 403", r.status_code == 403, str(r.status_code))

r = c.post("/clientes/1/excluir", data={"csrf_token": token()},
           follow_redirects=False)
chk("tecnico POST excluir -> 403", r.status_code == 403, str(r.status_code))

logout()
login(EMAIL_ADMIN, SENHA_ADMIN)

# ──────────────────────────────────────────────────────────────────────────────
# 3. Validação server-side (Pydantic)
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import query_one as q1

    antes = q1("SELECT COUNT(*) AS n FROM cliente WHERE D_E_L_E_T = 0")["n"]


def post_salvar(**dados):
    dados["csrf_token"] = token()
    return c.post("/clientes/salvar", data=dados, follow_redirects=False)


r = post_salvar(razao_social="Cliente Teste CPF Ruim", cpf_cnpj="11111111111")
chk("CPF com digito errado -> 422", r.status_code == 422, str(r.status_code))
chk("erro de campo aparece no form", b"CPF inv" in r.data)

r = post_salvar(razao_social="Cliente Teste Email Ruim", email="nao-e-email")
chk("email invalido -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(razao_social="Cliente Teste CEP Ruim", cep="01310")
chk("CEP invalido -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(razao_social="Cliente Teste CPF Ok", cpf_cnpj="11144477735")
# CPF "111.444.777-35" é o clássico VÁLIDO: formato e dígitos passam
chk("CPF valido passa na validacao", r.status_code == 302, f"{r.status_code} {r.data[:120]}")

with app.app_context():
    from core.db import query_one as q1

    depois = q1("SELECT COUNT(*) AS n FROM cliente WHERE D_E_L_E_T = 0")["n"]
chk("clientes invalidos nao gravaram", antes + 1 == depois,
    f"antes={antes} depois={depois}")

# ──────────────────────────────────────────────────────────────────────────────
# 4. Cadastro, edição, detalhe, Tag gerada e soft delete
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import query_one as q1

    linha = q1("SELECT id FROM cliente WHERE razao_social = 'Cliente Teste CPF Ok' "
               "AND D_E_L_E_T = 0")
    id_cli = linha["id"] if linha else 0
chk("cliente criado tem id", id_cli > 0, str(id_cli))

r = c.get(f"/clientes/{id_cli}")
chk("detalhe 200", r.status_code == 200, str(r.status_code))
chk("detalhe mostra estado vazio de equipamentos", b"Nenhum equipamento cadastrado" in r.data)

r = c.post(f"/clientes/{id_cli}/equipamentos",
           data={"csrf_token": token(), "patrimonio": "", "modelo": "Fogao 4 bocas",
                 "marca": "Lion"}, follow_redirects=False)
chk("equipamento com patrimonio vazio -> 302", r.status_code == 302, str(r.status_code))

with app.app_context():
    from core.db import query as ql

    eq = ql("SELECT id, patrimonio FROM equipamento WHERE id_cliente = ? "
            "AND D_E_L_E_T = 0", (id_cli,))
chk("backend gerou Tag ESG{id}", bool(eq) and eq[0]["patrimonio"] == f"ESG{eq[0]['id']}",
    eq[0]["patrimonio"] if eq else "sem equipamento")

r = c.get(f"/clientes/{id_cli}")
chk("detalhe lista o equipamento", b"Fogao 4 bocas" in r.data)

r = post_salvar(id=str(id_cli), razao_social="Cliente Teste Editado",
                cidade="São Paulo", uf="SP")
chk("edicao -> 302", r.status_code == 302, str(r.status_code))
r = c.get("/clientes/")
chk("edicao reflete na listagem", b"Cliente Teste Editado" in r.data)

r = c.post(f"/clientes/{id_cli}/excluir", data={"csrf_token": token()},
           follow_redirects=False)
chk("excluir -> 302", r.status_code == 302, str(r.status_code))
c.get("/clientes/")   # consome o flash ("X excluído" levaria o nome junto)
r = c.get("/clientes/")
chk("excluido some da listagem", b"Cliente Teste Editado" not in r.data)

with app.app_context():
    from core.db import query as ql

    morto = ql("SELECT D_E_L_E_T, deleted_at FROM cliente WHERE id = ?", (id_cli,))
chk("soft delete: D_E_L_E_T=1 e deleted_at preenchido",
    bool(morto) and morto[0]["D_E_L_E_T"] == 1 and bool(morto[0]["deleted_at"]),
    str(dict(morto[0])) if morto else "sumiu de vez")

r = c.get(f"/clientes/{id_cli}")
chk("detalhe do excluido -> 404 amigavel", r.status_code == 404, str(r.status_code))

# ──────────────────────────────────────────────────────────────────────────────
# 5. Preferências (TabelaAvancada), SelectBusca e CSRF
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import get_db

    db = get_db()
    db.execute("DELETE FROM usuario_preferencias WHERE chave = 'clientes'")
    db.commit()

r = c.get("/api/preferencia/clientes")
chk("preferencia GET vazia -> {}", r.status_code == 200 and r.get_json() == {},
    f"{r.status_code} {r.get_json()}")

r = c.post("/api/preferencia/clientes",
           headers={"X-CSRFToken": token(), "Content-Type": "application/json"},
           data='{"porPagina": 25, "ocultas": {"fantasia": true}}')
chk("preferencia POST (alias X-CSRFToken) -> ok",
    r.status_code == 200 and r.get_json().get("ok") is True, str(r.data[:80]))

r = c.get("/api/preferencia/clientes")
salva = r.get_json() or {}
chk("preferencia persistida", salva.get("porPagina") == 25
    and salva.get("ocultas", {}).get("fantasia") is True, str(salva))

r = c.get("/api/preferencia/cha%20ve!")
chk("chave com caractere invalido -> 400", r.status_code == 400, str(r.status_code))

r = c.get("/api/preferencia/..%2F..%2Fetc")
chk("path traversal na chave nao passa", r.status_code in (400, 404), str(r.status_code))

r = c.get("/clientes/api/cidades?q=paulo")
chk("SelectBusca cidades responde", r.status_code == 200
    and isinstance(r.get_json().get("itens"), list), str(r.data[:80]))

r = c.post("/clientes/salvar", data={"razao_social": "Sem CSRF"},
           follow_redirects=False)
with app.app_context():
    from core.db import query_one as q1

    tem = q1("SELECT id FROM cliente WHERE razao_social = 'Sem CSRF' AND D_E_L_E_T = 0")
chk("POST sem csrf nao grava", tem is None, str(tem))

# Foto: extensão errada vira erro de campo, não 500
import io  # noqa: E402

r = c.post("/clientes/salvar",
           data={"razao_social": "Cliente Foto", "csrf_token": token(),
                 "foto": (io.BytesIO(b"nao e imagem"), "nota.txt")},
           content_type="multipart/form-data", follow_redirects=False)
chk("foto .txt -> 422 com erro de campo", r.status_code == 422 and b"Formato" in r.data,
    str(r.status_code))

print()
print("FALHAS:", len(falhas))
sys.exit(1 if falhas else 0)
