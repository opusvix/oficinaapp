"""Fumaca Fase 5: Estoque de Peças (listagem, cadastro, validação, soft delete, movimento)."""
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

# Codigo únicos p/ esta execucao (evita colisao com execucoes anteriores)
CODIGO_TESTE = f"PEC{int(time.time())}"
CODIGO_BAIXA = f"BAIXA{int(time.time())}"

# ──────────────────────────────────────────────────────────────────────────────
# 1. Rotas e menu
# ──────────────────────────────────────────────────────────────────────────────

r = c.get("/estoque/")
chk("/estoque/ anon -> login",
    r.status_code == 302 and "/auth/login" in (r.headers.get("Location") or ""),
    str(r.headers.get("Location")))

r = login(EMAIL_ADMIN, SENHA_ADMIN)
chk("login admin", r.status_code == 302, str(r.status_code))

r = c.get("/estoque/")
chk("/estoque/ admin 200", r.status_code == 200, str(r.status_code))
chk("listagem usa TabelaAvancada", b"data-tabela" in r.data and b'data-pref-key="estoque"' in r.data)
chk("listagem tem botao nova peça", "Nova peça".encode() in r.data)
chk("listagem sem traceback", b"Traceback" not in r.data)

r = c.get("/home")
chk("menu acendeu /estoque/ (rota existe)", b'href="/estoque"' in r.data)
chk("menu sem hex da marca", b"#3387E9" not in r.data)

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

r = c.get("/estoque/")
chk("tecnico vê listagem (VER)", r.status_code == 200, str(r.status_code))
chk("tecnico sem botao nova peça", "Nova peça".encode() not in r.data)
chk("tecnico slot de exclusao desabilitado", 'class="btn btn-icone desabilitado"'.encode() in r.data)

r = c.post("/estoque/salvar", data={"codigo": "X", "csrf_token": token("/estoque/")},
           follow_redirects=False)
chk("tecnico POST salvar -> 403", r.status_code == 403, str(r.status_code))

logout()
login(EMAIL_ADMIN, SENHA_ADMIN)

# ──────────────────────────────────────────────────────────────────────────────
# 3. Validação server-side (Pydantic)
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import query_one as q1
    antes = q1("SELECT COUNT(*) AS n FROM peca WHERE D_E_L_E_T = 0")["n"]


def post_salvar(**dados):
    dados["csrf_token"] = token("/estoque/")
    return c.post("/estoque/salvar", data=dados, follow_redirects=False)


r = post_salvar(codigo="A", descricao="Desc ok")
chk("codigo muito curto -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(codigo="PEC001", descricao="D")
chk("descricao muito curta -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(codigo=CODIGO_TESTE, descricao="Peça Teste", preco_custo="abc")
chk("preco_custo invalido -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(codigo=CODIGO_TESTE, descricao="Peça Teste", unidade="XYZ")
chk("unidade invalida -> 422", r.status_code == 422, str(r.status_code))

r = post_salvar(codigo=CODIGO_TESTE, descricao="Peça Teste",
                preco_custo="10,00", preco_venda="20,00",
                estoque_atual="5", estoque_minimo="2")
chk("peca valida -> 302", r.status_code == 302, f"{r.status_code} {r.data[:120]}")

with app.app_context():
    from core.db import query_one as q1
    depois = q1("SELECT COUNT(*) AS n FROM peca WHERE D_E_L_E_T = 0")["n"]
chk("peca valida gravada", antes + 1 == depois, f"antes={antes} depois={depois}")

# pega id da peca criada
with app.app_context():
    from core.db import query_one as q1
    linha = q1(f"SELECT id FROM peca WHERE codigo = '{CODIGO_TESTE}' AND D_E_L_E_T = 0")
    id_peca = linha["id"] if linha else 0
chk("peca criada tem id", id_peca > 0, str(id_peca))

# ──────────────────────────────────────────────────────────────────────────────
# 4. Detalhe, entrada/saída, soft delete
# ──────────────────────────────────────────────────────────────────────────────

r = c.get(f"/estoque/{id_peca}")
chk("detalhe 200", r.status_code == 200, str(r.status_code))

# entrada
r = c.post(f"/estoque/{id_peca}/movimento",
           data={"csrf_token": token(f"/estoque/{id_peca}"), "tipo": "ENTRADA",
                 "quantidade": "10", "observacoes": "Reposicao"},
           follow_redirects=False)
chk("entrada -> 302", r.status_code == 302, str(r.status_code))

r = c.get(f"/estoque/{id_peca}")
chk("detalhe lista movimento", b"Reposicao" in r.data and b"ENTRADA" in r.data)

# saída maior que estoque -> erro (flash na pagina de listagem)
r = c.post(f"/estoque/{id_peca}/movimento",
           data={"csrf_token": token(f"/estoque/{id_peca}"), "tipo": "SAIDA",
                 "quantidade": "999"},
           follow_redirects=True)
chk("saida acima do estoque -> flash erro",
    b"Estoque insuficiente" in r.data, str(r.status_code))

# saída válida
r = c.post(f"/estoque/{id_peca}/movimento",
           data={"csrf_token": token(f"/estoque/{id_peca}"), "tipo": "SAIDA",
                 "quantidade": "3"},
           follow_redirects=False)
chk("saida valida -> 302", r.status_code == 302, str(r.status_code))

# edição
r = post_salvar(id=str(id_peca), codigo=CODIGO_TESTE, descricao="Peça Teste Editada",
                preco_custo="10,00", preco_venda="20,00",
                estoque_atual="5", estoque_minimo="2")
chk("edicao -> 302", r.status_code == 302, str(r.status_code))
r = c.get("/estoque/")
chk("edicao reflete na listagem", "Peça Teste Editada".encode() in r.data)

# excluir
r = c.post(f"/estoque/{id_peca}/excluir", data={"csrf_token": token("/estoque/")},
           follow_redirects=False)
chk("excluir -> 302", r.status_code == 302, str(r.status_code))
r = c.get("/estoque/")
chk("excluido some da listagem", "Peça Teste Editada".encode() not in r.data)

with app.app_context():
    from core.db import query as ql
    morto = ql("SELECT D_E_L_E_T, deleted_at FROM peca WHERE id = ?", (id_peca,))
chk("soft delete: D_E_L_E_T=1 e deleted_at preenchido",
    bool(morto) and morto[0]["D_E_L_E_T"] == 1 and bool(morto[0]["deleted_at"]),
    str(dict(morto[0])) if morto else "sumiu de vez")

# ──────────────────────────────────────────────────────────────────────────────
# 5. Badge de estoque baixo
# ──────────────────────────────────────────────────────────────────────────────

with app.app_context():
    from core.db import get_db
    db = get_db()
    db.execute("INSERT INTO peca (codigo, descricao, unidade, preco_custo, preco_venda, "
               "estoque_atual, estoque_minimo) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (CODIGO_BAIXA, "Peça estoque baixo", "UN", "10,00", "20,00", "1", "5"))
    db.commit()

r = c.get("/estoque/")
chk("badge estoque baixo aparece", b"badge-vermelho" in r.data, "nao achou badge-vermelho")

print()
print("FALHAS:", len(falhas))
sys.exit(1 if falhas else 0)
