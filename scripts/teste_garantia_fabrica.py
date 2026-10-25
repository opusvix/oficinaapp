"""Prova do fluxo "Garantia de Fábrica" (status inicial + cobrança do fabricante).

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_garantia_fabrica.py
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
os.environ.pop("MODO_DEMO", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402
from modules.validacao_os import OSIn  # noqa: E402

app = create_app()
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def sql(q, p=()):
    with app.app_context():
        from core.db import get_db
        db = get_db()
        cur = db.execute(q, p)
        rows = cur.fetchall() if q.strip().lower().startswith("select") or "returning" in q.lower() else None
        db.commit()
        return rows


# ── Dados base ────────────────────────────────────────────────────────────────
cli = sql("INSERT INTO cliente (razao_social, cpf_cnpj) VALUES ('Padaria Teste', '22333444000181') RETURNING id")[0][0]
equip = sql("INSERT INTO equipamento (id_cliente, patrimonio, modelo, marca) "
            "VALUES (?, 'ESG900', 'Forno combinado', 'Electrolux') RETURNING id", (cli,))[0][0]
peca = sql("INSERT INTO peca (codigo, descricao, estoque_atual, estoque_minimo) "
           "VALUES ('P-900', 'Resistência', 10, 2) RETURNING id")[0][0]


def nova_os(status, garantia, desloc="0", orcamento="0", id_equip=equip):
    id_os = sql(
        "INSERT INTO ordem_servico (id_cliente, id_equipamento, patrimonio, status, garantia_fabrica, "
        "orcamento_status, orcamento_valor, custo_deslocamento, descricao_inicial) "
        "VALUES (?, ?, 'ESG900', ?, ?, 'pendente', ?, ?, 'teste') RETURNING id",
        (cli, id_equip, status, garantia, orcamento, desloc),
    )[0][0]
    return id_os


# ── 1. Whitelist de status inicial (Mass_Assignment) ──────────────────────────
def status_ok(v):
    try:
        OSIn(id_cliente="1", descricao_inicial="teste problema aqui", status=v)
        return True
    except Exception:
        return False

chk("status inicial aceita 'garantia_fabrica'", status_ok("garantia_fabrica"))
chk("status inicial aceita 'avaliacao'", status_ok("avaliacao"))
chk("status inicial REJEITA 'aberta' (saiu das opções)", not status_ok("aberta"))
chk("status inicial REJEITA 'entregue' (forjado)", not status_ok("entregue"))
chk("status inicial default = avaliacao",
    OSIn(id_cliente="1", descricao_inicial="teste problema aqui").status == "avaliacao")

# ── 2. Rótulos ────────────────────────────────────────────────────────────────
from modules.os import ROTULOS_STATUS  # noqa: E402
chk("rótulo 'Aguardando avaliação'", ROTULOS_STATUS["avaliacao"] == "Aguardando avaliação")
chk("rótulo 'Garantia de Fábrica'", ROTULOS_STATUS["garantia_fabrica"] == "Garantia de Fábrica")

# ── 3. Cobrança do fabricante (sem cliente, mão de obra + deslocamento) ────────
id_g = nova_os("garantia_fabrica", 1, desloc="20", orcamento="100")
with app.app_context():
    from core.db import get_db
    from modules.financeiro import gerar_recebivel_os
    db = get_db()
    gerar_recebivel_os(db, id_g, "entregue")
    db.commit()
rec = sql("SELECT valor, id_cliente, descricao, tipo FROM financeiro WHERE id_os = ?", (id_g,))
chk("garantia gera 1 recebível", len(rec) == 1, rec)
if rec:
    chk("garantia: valor = mão de obra + deslocamento (120)", float(rec[0][0]) == 120.0, rec[0][0])
    chk("garantia: SEM cliente (não é dívida do cliente)", rec[0][1] is None, rec[0][1])
    chk("garantia: descrição cita o fabricante (marca)", "Electrolux" in (rec[0][2] or ""), rec[0][2])

# ── 4. Garantia NÃO baixa estoque ─────────────────────────────────────────────
id_g2 = nova_os("garantia_fabrica", 1)
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario, subtotal) "
    "VALUES (?, ?, 'Resistência', 2, 0, 0)", (id_g2, peca))
antes = sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0]
with app.app_context():
    from core.db import get_db
    from modules.os import _baixa_estoque
    db = get_db()
    _baixa_estoque(db, id_g2)
    db.commit()
depois = sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0]
mov = sql("SELECT COUNT(*) FROM movimento_estoque WHERE id_origem = ?", (id_g2,))[0][0]
chk("garantia: estoque NÃO muda", float(antes) == float(depois), f"{antes}->{depois}")
chk("garantia: nenhum movimento de estoque", mov == 0, mov)

# ── Login admin pros testes de rota ───────────────────────────────────────────
sql("UPDATE usuario SET precisa_trocar_senha = 0 WHERE email = 'admin@teste.local'")
adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/home").data).group(1).decode()

# ── 5. Fabricante AUTORIZA ────────────────────────────────────────────────────
id_a = nova_os("garantia_fabrica", 1)
adm.post(f"/os/{id_a}/fabricante", data={"decisao": "autorizar", "csrf_token": TK})
row = sql("SELECT status, orcamento_status, garantia_fabrica FROM ordem_servico WHERE id = ?", (id_a,))[0]
chk("autorizar: status -> aprovada", row[0] == "aprovada", row[0])
chk("autorizar: orçamento -> aprovado (não consulta cliente)", row[1] == "aprovado", row[1])
chk("autorizar: segue sendo garantia (flag 1)", row[2] == 1, row[2])

# ── 6. Fabricante REPROVA -> vira do cliente ──────────────────────────────────
id_r = nova_os("garantia_fabrica", 1)
adm.post(f"/os/{id_r}/fabricante", data={"decisao": "reprovar", "csrf_token": TK})
row = sql("SELECT status, orcamento_status, garantia_fabrica FROM ordem_servico WHERE id = ?", (id_r,))[0]
chk("reprovar: status -> avaliacao (volta pro cliente)", row[0] == "avaliacao", row[0])
chk("reprovar: deixa de ser garantia (flag 0)", row[2] == 0, row[2])
chk("reprovar: orçamento volta a pendente (cliente aprova)", row[1] == "pendente", row[1])

# ── 7. Regressão: OS normal cobra o CLIENTE e baixa estoque ───────────────────
id_n = nova_os("avaliacao", 0, desloc="10", orcamento="50")
with app.app_context():
    from core.db import get_db
    from modules.financeiro import gerar_recebivel_os
    db = get_db()
    gerar_recebivel_os(db, id_n, "entregue")
    db.commit()
recn = sql("SELECT valor, id_cliente FROM financeiro WHERE id_os = ?", (id_n,))
chk("normal: recebível COM cliente (regressão)", recn and recn[0][1] is not None, recn)

id_n2 = nova_os("avaliacao", 0)
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario, subtotal) "
    "VALUES (?, ?, 'Resistência', 1, 0, 0)", (id_n2, peca))
e_antes = sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0]
with app.app_context():
    from core.db import get_db
    from modules.os import _baixa_estoque
    db = get_db()
    _baixa_estoque(db, id_n2)
    db.commit()
e_depois = sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0]
chk("normal: estoque baixa (regressão)", float(e_depois) == float(e_antes) - 1, f"{e_antes}->{e_depois}")

# ── 8. nova() via tela grava a flag de garantia ───────────────────────────────
adm.post("/os/nova", data={"id_cliente": str(cli), "id_equipamento": str(equip),
                           "descricao_inicial": "não liga de jeito nenhum",
                           "custo_deslocamento": "0", "status": "garantia_fabrica", "csrf_token": TK})
ult = sql("SELECT status, garantia_fabrica FROM ordem_servico ORDER BY id DESC LIMIT 1")[0]
chk("nova OS garantia: status garantia_fabrica", ult[0] == "garantia_fabrica", ult[0])
chk("nova OS garantia: flag gravada = 1", ult[1] == 1, ult[1])

# ── Sanidade ──────────────────────────────────────────────────────────────────
chk("dev DB nunca é o oficina.db (sanidade)", "oficina.db" not in os.environ["FLASK_DATABASE"])

print()
if falhas:
    print(f"RESULTADO: {len(falhas)} FALHA(S) — " + "; ".join(falhas))
    sys.exit(1)
print("RESULTADO: todos os casos passaram.")
sys.exit(0)
