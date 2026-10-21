"""Fumaca Fase 6: Ordens de Serviço (core)."""
import re
import sys
import time

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


def token(url="/auth/login"):
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

# Codigo único p/ esta execucao
TS = str(int(time.time()))

# Limpa OS de execucoes anteriores
with app.app_context():
    from core.db import get_db
    db = get_db()
    db.execute("DELETE FROM item_os WHERE id_os IN (SELECT id FROM ordem_servico WHERE D_E_L_E_T = 0)")
    db.execute("DELETE FROM ordem_servico WHERE D_E_L_E_T = 0")
    db.commit()

# ──────────────────────────────────────────────────────────────────────────────
# 1. Rotas e menu
# ──────────────────────────────────────────────────────────────────────────────

r = c.get("/os/")
chk("/os/ anon -> login",
    r.status_code == 302 and "/auth/login" in (r.headers.get("Location") or ""),
    str(r.headers.get("Location")))

r = login(EMAIL_ADMIN, SENHA_ADMIN)
chk("login admin", r.status_code == 302, str(r.status_code))

r = c.get("/os/")
chk("/os/ admin 200", r.status_code == 200, str(r.status_code))
chk("listagem usa TabelaAvancada", b"data-tabela" in r.data and b'data-pref-key="os_listagem"' in r.data)
chk("listagem tem botao Nova OS", "Nova OS".encode() in r.data)
chk("listagem sem traceback", b"Traceback" not in r.data)

r = c.get("/home")
chk("menu acendeu /os/ (rota existe)", b'href="/os"' in r.data)
chk("menu sem hex da marca", b"#3387E9" not in r.data)

# ──────────────────────────────────────────────────────────────────────────────
# 2. Perfil tecnico: VER e EDITAR (seed permite tecnico editar OS)
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
                   ("Tecnico de Teste", "tecnico.teste@oficina.local", senha_hash))
        db.commit()

logout()
r = login("tecnico.teste@oficina.local", "TecnicoTeste2026!")
chk("login tecnico", r.status_code == 302, str(r.status_code))

r = c.get("/os/")
chk("tecnico vê listagem (VER)", r.status_code == 200, str(r.status_code))
# tecnico tem pode_editar=True p/ OS (seed linha 72), entao VE botao Nova OS
chk("tecnico VÊ botao Nova OS (pode editar)", "Nova OS".encode() in r.data)

logout()
login(EMAIL_ADMIN, SENHA_ADMIN)

# ──────────────────────────────────────────────────────────────────────────────
# 3. Garante cliente e equipamento de teste
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import get_db
    db = get_db()
    cl = db.execute("SELECT id, razao_social FROM cliente WHERE D_E_L_E_T = 0 LIMIT 1").fetchone()
    if cl is None:
        db.execute("INSERT INTO cliente (razao_social, cpf_cnpj) VALUES (?, ?)",
                   ("Cliente Teste OS", "11144477735"))
        db.commit()
        cl = db.execute("SELECT id, razao_social FROM cliente WHERE D_E_L_E_T = 0 LIMIT 1").fetchone()
    id_cliente = cl["id"]
    nome_cliente = cl["razao_social"]

    eq = db.execute("SELECT id FROM equipamento WHERE id_cliente = ? AND D_E_L_E_T = 0 LIMIT 1",
                    (id_cliente,)).fetchone()
    if eq is None:
        db.execute("INSERT INTO equipamento (id_cliente, patrimonio, modelo) VALUES (?, ?, ?)",
                   (id_cliente, f"EQP{TS}", "Geladeira Teste"))
        db.commit()
        eq = db.execute("SELECT id FROM equipamento WHERE id_cliente = ? AND D_E_L_E_T = 0 LIMIT 1",
                        (id_cliente,)).fetchone()
    id_equipamento = eq["id"]

# ──────────────────────────────────────────────────────────────────────────────
# 4. Criacao de OS sem patrimonio -> gera ESG{idOS}
# ──────────────────────────────────────────────────────────────────────────────

r = c.post("/os/nova", data={
    "csrf_token": token("/os/nova"),
    "id_cliente": str(id_cliente),
    "id_equipamento": str(id_equipamento),
    "patrimonio": "",
    "descricao_inicial": "Geladeira nao gela",
    "orcamento_valor": "0",
    "custo_deslocamento": "0",
    "status": "aberta",
}, follow_redirects=False)
chk("OS sem patrimonio -> 302", r.status_code == 302, f"{r.status_code} {r.data[:120]}")

with app.app_context():
    from core.db import query_one as q1
    os_row = q1("SELECT id, patrimonio, descricao_inicial FROM ordem_servico WHERE descricao_inicial = 'Geladeira nao gela' AND D_E_L_E_T = 0 ORDER BY id DESC LIMIT 1")
    id_os = os_row["id"] if os_row else 0
    patrimonio_gerado = os_row["patrimonio"] if os_row else None
chk("OS criada com id", id_os > 0, str(id_os))
chk("patrimonio gerado ESG{idOS}",
    patrimonio_gerado == f"ESG{id_os}",
    f"esperado ESG{id_os}, obtido {patrimonio_gerado}")

# ──────────────────────────────────────────────────────────────────────────────
# 5. Criacao de OS com patrimonio informado
# ──────────────────────────────────────────────────────────────────────────────

r = c.post("/os/nova", data={
    "csrf_token": token("/os/nova"),
    "id_cliente": str(id_cliente),
    "id_equipamento": str(id_equipamento),
    "patrimonio": f"PAT{TS}",
    "descricao_inicial": "Fogao nao acende",
    "orcamento_valor": "150,00",
    "custo_deslocamento": "50,00",
    "status": "aberta",
}, follow_redirects=False)
chk("OS com patrimonio -> 302", r.status_code == 302, str(r.status_code))

with app.app_context():
    from core.db import query_one as q1
    os2 = q1("SELECT id FROM ordem_servico WHERE patrimonio = ? AND D_E_L_E_T = 0", (f"PAT{TS}",))
    id_os2 = os2["id"] if os2 else 0
chk("OS com patrimonio criada", id_os2 > 0, str(id_os2))

# ──────────────────────────────────────────────────────────────────────────────
# 6. Detalhe da OS
# ──────────────────────────────────────────────────────────────────────────────

r = c.get(f"/os/{id_os}")
chk("detalhe OS 200", r.status_code == 200, str(r.status_code))
chk("detalhe mostra descricao", "Geladeira nao gela".encode() in r.data)
chk("detalhe mostra patrimonio", f"ESG{id_os}".encode() in r.data)

# ──────────────────────────────────────────────────────────────────────────────
# 7. Adicionar item à OS
# ──────────────────────────────────────────────────────────────────────────────

r = c.post(f"/os/{id_os}/item", data={
    "csrf_token": token(f"/os/{id_os}"),
    "descricao": "Filtro de ar",
    "quantidade": "2",
    "preco_unitario": "30,00",
}, follow_redirects=False)
chk("adicionar item -> 302", r.status_code == 302, str(r.status_code))

r = c.get(f"/os/{id_os}")
chk("detalhe lista item", "Filtro de ar".encode() in r.data)

# ──────────────────────────────────────────────────────────────────────────────
# 8. Token de aprovacao + link publico
# ──────────────────────────────────────────────────────────────────────────────

r = c.post(f"/os/{id_os}/token", data={"csrf_token": token(f"/os/{id_os}")}, follow_redirects=False)
chk("gerar token -> 302", r.status_code == 302, str(r.status_code))

with app.app_context():
    from core.db import query_one as q1
    tok = q1("SELECT os_token FROM ordem_servico WHERE id = ?", (id_os,))
    token_valor = tok["os_token"] if tok else ""
chk("token gerado", bool(token_valor), str(token_valor))

# link publico - visualizar
r = c.get(f"/os/public/{token_valor}")
chk("link publico 200", r.status_code == 200, str(r.status_code))
chk("link publico mostra cliente", nome_cliente.encode() in r.data)

# link publico - recusar orcamento
r = c.post(f"/os/public/{token_valor}", data={
    "csrf_token": token(f"/os/public/{token_valor}"),
    "decisão": "recusar",
}, follow_redirects=False)
chk("recusar orcamento -> 302", r.status_code == 302, str(r.status_code))

with app.app_context():
    from core.db import query_one as q1
    st = q1("SELECT orcamento_status, status FROM ordem_servico WHERE id = ?", (id_os,))
    chk("orcamento recusado no banco",
        bool(st) and st["orcamento_status"] == "recusado" and st["status"] == "recusada",
        str(dict(st)) if st else "sem OS")

print()
print("FALHAS:", len(falhas))
sys.exit(1 if falhas else 0)
