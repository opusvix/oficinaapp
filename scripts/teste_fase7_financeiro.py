"""Prova da Fase 7: Financeiro + PDV.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_fase7_financeiro.py
Sai com código 1 se algum caso falhar.
"""
import base64
import os
import re
import struct
import sys
import tempfile
import zlib
from datetime import date, timedelta
from decimal import Decimal

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402
from core.tempo import hoje_local  # noqa: E402

app = create_app()
falhas = []
HOJE = hoje_local()


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def sql(q, p=()):
    with app.app_context():
        from core.db import get_db
        db = get_db()
        linhas = db.execute(q, p).fetchall()
        db.commit()
        return linhas


def png(larg=520, alt=180):
    linhas = b"".join(b"\x00" + bytes(0 if (x * 7 + y * 13) % 29 == 0 else 255 for x in range(larg)) for y in range(alt))
    def b(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + b(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 0, 0, 0, 0))
            + b(b"IDAT", zlib.compress(linhas)) + b(b"IEND", b""))


sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) VALUES ('Tec', 'tec@teste.local', ?, 2, 0)", (h,))
cli = sql("INSERT INTO cliente (razao_social, cpf_cnpj) VALUES ('Lanchonete Teste', '22333444000181') RETURNING id")[0][0]

adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/financeiro/receber").data).group(1).decode()


def post(c, url, **dados):
    return c.post(url, data={**dados, "csrf_token": TK})


def tit(id_):
    return sql("SELECT * FROM financeiro WHERE id = ?", (id_,))[0]


def gaveta():
    from modules.financeiro import caixa_aberto, resumo_caixa
    with app.app_context():
        cx = caixa_aberto()
        return resumo_caixa(cx["id"])["gaveta"] if cx else None


# ── 1. Telas e menu ──────────────────────────────────────────────────────────
for url in ("/financeiro/", "/financeiro/receber", "/financeiro/pagar", "/financeiro/caixa"):
    r = adm.get(url)
    chk(f"admin abre {url}", r.status_code == 200, r.status_code)
html = adm.get("/home").data.decode()
chk("menu acendeu Financeiro (rota existe, sai do 'em breve')", 'href="/financeiro/caixa"' in html or 'href="/financeiro"' in html)

# ── 2. Lançamento com parcelas ───────────────────────────────────────────────
post(adm, "/financeiro/titulo/novo", tipo="RECEBER", descricao="Contrato de manutenção", valor="100,00",
     data_vencimento="2026-01-31", parcelas="3", id_cliente=str(cli))
ps = sql("SELECT valor, data_vencimento, descricao, parcela, total_parcelas FROM financeiro "
         "WHERE descricao LIKE 'Contrato de manutenção%' ORDER BY parcela")
chk("3 parcelas criadas", len(ps) == 3, len(ps))
chk("parcelas somam o total exato (33,33 + 33,33 + 33,34)",
    [Decimal(str(p[0])).quantize(Decimal("0.01")) for p in ps] == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")],
    [p[0] for p in ps])
chk("vencimentos mensais e 31/01 vira 28/02", [p[1] for p in ps] == ["2026-01-31", "2026-02-28", "2026-03-31"],
    [p[1] for p in ps])
chk("descrição numera a parcela (1/3)", ps[0][2].endswith("(1/3)"))
r = post(adm, "/financeiro/titulo/novo", tipo="RECEBER", descricao="Valor zero", valor="0", data_vencimento=str(HOJE))
chk("valor zero é recusado", not sql("SELECT 1 FROM financeiro WHERE descricao = 'Valor zero'"))

id_rec = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, id_cliente) "
             "VALUES ('RECEBER', 'Venda de peça', 80, ?, ?) RETURNING id", (str(HOJE), cli))[0][0]
id_pix = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento) "
             "VALUES ('RECEBER', 'Conserto pago no pix', 150, ?) RETURNING id", (str(HOJE),))[0][0]
id_pag = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, fornecedor) "
             "VALUES ('PAGAR', 'Fio de silicone', 20, ?, 'Distribuidora') RETURNING id", (str(HOJE),))[0][0]

# ── 3. Baixa: dinheiro exige caixa ───────────────────────────────────────────
post(adm, f"/financeiro/titulo/{id_rec}/baixar", forma_pagamento="dinheiro", data_pagamento=str(HOJE))
chk("baixa em dinheiro SEM caixa aberto é recusada", tit(id_rec)["status"] == "aberto")
post(adm, f"/financeiro/titulo/{id_pix}/baixar", forma_pagamento="pix", data_pagamento=str(HOJE))
chk("baixa em pix sem caixa passa", tit(id_pix)["status"] == "pago" and tit(id_pix)["forma_pagamento"] == "pix")
post(adm, f"/financeiro/titulo/{id_rec}/baixar", forma_pagamento="dinheiro",
     data_pagamento=str(HOJE + timedelta(days=1)))
chk("baixa com data no futuro é recusada", tit(id_rec)["status"] == "aberto")

# ── 4. Caixa ─────────────────────────────────────────────────────────────────
post(adm, "/financeiro/caixa/abrir", valor="50,00")
chk("caixa aberto com troco de 50", gaveta() == Decimal("50.00"), gaveta())
post(adm, "/financeiro/caixa/abrir", valor="10,00")
chk("só UM caixa aberto por vez", len(sql("SELECT 1 FROM caixa WHERE status = 'aberto'")) == 1)
post(adm, f"/financeiro/titulo/{id_rec}/baixar", forma_pagamento="dinheiro", data_pagamento=str(HOJE))
chk("baixa em dinheiro com caixa: pago e entra na gaveta (50 + 80)",
    tit(id_rec)["status"] == "pago" and gaveta() == Decimal("130.00"), (tit(id_rec)["status"], gaveta()))
post(adm, f"/financeiro/titulo/{id_rec}/baixar", forma_pagamento="dinheiro", data_pagamento=str(HOJE))
chk("baixa duplicada não entra de novo na gaveta", gaveta() == Decimal("130.00"), gaveta())
id_grande = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, status) "
                "VALUES ('PAGAR', 'Conta grande', 500, ?, 'aberto') RETURNING id", (str(HOJE),))[0][0]
post(adm, f"/financeiro/titulo/{id_grande}/baixar", forma_pagamento="dinheiro", data_pagamento=str(HOJE))
chk("pagar em dinheiro mais do que tem na gaveta é recusado (500 > 130)",
    tit(id_grande)["status"] == "aberto" and gaveta() == Decimal("130.00"), (tit(id_grande)["status"], gaveta()))
sql("UPDATE financeiro SET D_E_L_E_T = 1 WHERE id = ?", (id_grande,))
post(adm, f"/financeiro/titulo/{id_pag}/baixar", forma_pagamento="dinheiro", data_pagamento=str(HOJE))
chk("pagamento em dinheiro sai da gaveta (130 - 20)", gaveta() == Decimal("110.00"), gaveta())
post(adm, "/financeiro/caixa/movimento", tipo="SUPRIMENTO", valor="10", descricao="reforço de troco")
chk("suprimento entra (110 + 10)", gaveta() == Decimal("120.00"), gaveta())
post(adm, "/financeiro/caixa/movimento", tipo="SANGRIA", valor="500", descricao="depósito")
chk("sangria maior que a gaveta é recusada", gaveta() == Decimal("120.00"), gaveta())
post(adm, "/financeiro/caixa/movimento", tipo="SANGRIA", valor="20", descricao="")
chk("sangria sem motivo é recusada", gaveta() == Decimal("120.00"), gaveta())
post(adm, "/financeiro/caixa/movimento", tipo="SANGRIA", valor="20", descricao="depósito no banco")
chk("sangria com motivo sai (120 - 20)", gaveta() == Decimal("100.00"), gaveta())
r = adm.get("/financeiro/caixa").data.decode()
chk("tela do caixa mostra a gaveta em real", "R$ 100,00" in r)

# ── 5. Parcelar e cancelar ───────────────────────────────────────────────────
id_par = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento) "
             "VALUES ('RECEBER', 'Reforma completa', 1000, ?) RETURNING id", (str(HOJE),))[0][0]
post(adm, f"/financeiro/titulo/{id_par}/parcelar", parcelas="4")
filhos = sql("SELECT valor FROM financeiro WHERE id_origem = ?", (id_par,))
chk("parcelar: original vira 'parcelado' e nascem 4 parcelas que somam 1000",
    tit(id_par)["status"] == "parcelado" and len(filhos) == 4 and sum(Decimal(str(f[0])) for f in filhos) == 1000,
    (tit(id_par)["status"], len(filhos)))
post(adm, f"/financeiro/titulo/{id_par}/parcelar", parcelas="2")
chk("título já parcelado não parcela de novo", len(sql("SELECT 1 FROM financeiro WHERE id_origem = ?", (id_par,))) == 4)
id_can = sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento) "
             "VALUES ('PAGAR', 'Conta errada', 99, ?) RETURNING id", (str(HOJE),))[0][0]
post(adm, f"/financeiro/titulo/{id_can}/cancelar")
chk("cancelar título aberto: status cancelado, linha mantida", tit(id_can)["status"] == "cancelado"
    and tit(id_can)["D_E_L_E_T"] == 0)
post(adm, f"/financeiro/titulo/{id_rec}/cancelar")
chk("título pago não é cancelado", tit(id_rec)["status"] == "pago")

# ── 6. Fechar caixa com diferença ────────────────────────────────────────────
post(adm, "/financeiro/caixa/fechar", valor="99,00", descricao="faltou 1 real")
cx = sql("SELECT status, saldo_calculado, saldo_informado, diferenca FROM caixa ORDER BY id DESC LIMIT 1")[0]
chk("fechar: sistema 100, contado 99, diferença -1", cx[0] == "fechado" and float(cx[1]) == 100 and float(cx[2]) == 99
    and float(cx[3]) == -1, tuple(cx))
chk("caixa fechado aparece no histórico com a diferença", "-R$ 1,00" in adm.get("/financeiro/caixa").data.decode())

# ── 7. OS gera recebível ─────────────────────────────────────────────────────
def os_pronta(desloc, itens):
    id_os = sql("INSERT INTO ordem_servico (id_cliente, patrimonio, status, orcamento_status, descricao_inicial, "
                "descricao_execucao, testado_funcionamento, foto_depois, entrega_solicitada_em, os_token, token_expira, "
                "custo_deslocamento) VALUES (?, 'P', 'em_andamento', 'aprovado', 'x', 'feito', 1, 'uploads/os/x.png', "
                "CURRENT_TIMESTAMP, ?, '2099-01-01 00:00:00', ?) RETURNING id",
                (cli, f"tok{desloc}{itens}", desloc))[0][0]
    sql("INSERT INTO item_os (id_os, descricao, quantidade, preco_unitario, subtotal) VALUES (?, 'Serviço', 1, ?, ?)",
        (id_os, itens, itens))
    sql("UPDATE ordem_servico SET orcamento_valor = ? WHERE id = ?", (itens, id_os))
    return id_os, f"tok{desloc}{itens}"


pub = app.test_client()
id_os, tok = os_pronta(30, 211)
r = pub.get(f"/os/public/{tok}")
tkp = re.search(rb'name="csrf_token" value="([^"]+)"', r.data).group(1).decode()
ass = "data:image/png;base64," + base64.b64encode(png()).decode()
pub.post(f"/os/public/{tok}", data={"decisao": "entregue", "assinatura": ass, "csrf_token": tkp})
rec = sql("SELECT valor, id_cliente, tipo, status, data_vencimento FROM financeiro WHERE id_os = ?", (id_os,))
chk("OS entregue gera 1 recebível de orçamento + deslocamento (211 + 30 = 241)",
    len(rec) == 1 and float(rec[0][0]) == 241 and rec[0][1] == cli and rec[0][2] == "RECEBER" and rec[0][3] == "aberto",
    [tuple(x) for x in rec])
chk("recebível da OS vence hoje", rec and rec[0][4] == str(HOJE))
with app.app_context():
    from core.db import get_db
    from modules.financeiro import gerar_recebivel_os
    db = get_db()
    gerar_recebivel_os(db, id_os, "entregue")
    db.commit()
chk("chamar de novo não duplica o recebível", len(sql("SELECT 1 FROM financeiro WHERE id_os = ?", (id_os,))) == 1)

id_rec_os = sql("INSERT INTO ordem_servico (id_cliente, patrimonio, status, orcamento_status, descricao_inicial, "
                "os_token, token_expira, custo_deslocamento) VALUES (?, 'R', 'avaliacao', 'pendente', 'x', 'tokrec', "
                "'2099-01-01 00:00:00', 40) RETURNING id", (cli,))[0][0]
r = pub.get("/os/public/tokrec")
tkp = re.search(rb'name="csrf_token" value="([^"]+)"', r.data).group(1).decode()
pub.post("/os/public/tokrec", data={"decisao": "recusar", "csrf_token": tkp})
rec = sql("SELECT valor, descricao FROM financeiro WHERE id_os = ?", (id_rec_os,))
chk("OS recusada gera só o deslocamento (40)", len(rec) == 1 and float(rec[0][0]) == 40 and "deslocamento" in rec[0][1],
    [tuple(x) for x in rec])

# ── 8. Recibo ────────────────────────────────────────────────────────────────
r = adm.get(f"/financeiro/recibo/{id_rec}")
chk("recibo de título recebido abre com valor e cliente", r.status_code == 200 and "R$ 80,00" in r.data.decode()
    and "Lanchonete Teste" in r.data.decode())
chk("recibo mostra o CNPJ com máscara", "22.333.444/0001-81" in r.data.decode())
chk("recibo de título em aberto -> 404", adm.get(f"/financeiro/recibo/{id_par}").status_code == 404)
chk("recibo de conta a PAGAR -> 404", adm.get(f"/financeiro/recibo/{id_pag}").status_code == 404)

# ── 9. Dashboard e listagens ─────────────────────────────────────────────────
html = adm.get("/financeiro/").data.decode()
chk("dashboard tem 6 KPIs", html.count('class="mg-kpi ') == 6, html.count('class="mg-kpi '))
chk("dashboard: recebido no período inclui pix 150 + dinheiro 80 = R$ 230,00", "R$ 230,00" in html)
chk("dashboard abre em 'Mês atual' com rótulo 'Pagamento'", re.search(r'value="mes"\s+class="on"', html) is not None
    and ">Pagamento<" in html)
for url in ("/financeiro/receber", "/financeiro/pagar"):
    html = adm.get(url).data.decode()
    chk(f"{url} sem KPI (listagem operacional)", "mg-kpi" not in html)
    chk(f"{url} sem <select> nativo", "<select" not in html)
sql("UPDATE financeiro SET data_vencimento = ? WHERE descricao = 'Contrato de manutenção (1/3)'",
    (str(HOJE - timedelta(days=5)),))
html = adm.get("/financeiro/receber?status=vencido&periodo=todos").data.decode()
chk("filtro Vencidos mostra o título atrasado", "Contrato de manutenção (1/3)" in html and "Vencido" in html)
html = adm.get("/financeiro/").data.decode()
qtd_venc = sql("SELECT COUNT(*) FROM financeiro WHERE tipo='RECEBER' AND status='aberto' AND D_E_L_E_T=0 "
               "AND data_vencimento < ?", (str(HOJE),))[0][0]
chk(f"dashboard acende Inadimplência (card neg) com {qtd_venc} títulos vencidos",
    'mg-kpi neg' in html and f"{qtd_venc} títulos vencidos" in html, qtd_venc)

# ── 10. Permissões e mass assignment ─────────────────────────────────────────
tec = app.test_client()
tec.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
chk("técnico vê o dashboard (VER financeiro)", tec.get("/financeiro/").status_code == 200)
chk("técnico NÃO vê contas a receber", tec.get("/financeiro/receber").status_code == 403)
chk("técnico NÃO vê o caixa", tec.get("/financeiro/caixa").status_code == 403)
tk2 = re.search(rb'name="csrf-token" content="([^"]+)"', tec.get("/financeiro/").data).group(1).decode()
r = tec.post("/financeiro/titulo/novo", data={"tipo": "RECEBER", "descricao": "hack", "valor": "1",
                                               "data_vencimento": str(HOJE), "csrf_token": tk2})
chk("técnico NÃO lança título -> 403", r.status_code == 403, r.status_code)
post(adm, "/financeiro/titulo/novo", tipo="PAGAR", descricao="Teste de campo extra", valor="10",
     data_vencimento=str(HOJE), status="pago", id_caixa="1")
t = sql("SELECT status, id_caixa FROM financeiro WHERE descricao = 'Teste de campo extra'")
chk("campos extras do form (status=pago) são ignorados: título nasce aberto", t and t[0][0] == "aberto" and t[0][1] is None,
    [tuple(x) for x in t])
n_antes = len(sql("SELECT 1 FROM financeiro"))
r = adm.post("/financeiro/titulo/novo", data={"tipo": "RECEBER", "descricao": "sem token", "valor": "5",
                                               "data_vencimento": str(HOJE)})
chk("POST do financeiro sem token CSRF não grava nada", r.status_code in (302, 400) and len(sql("SELECT 1 FROM financeiro")) == n_antes,
    r.status_code)
chk("auditoria registra baixa e caixa", len(sql("SELECT 1 FROM logs_acesso WHERE acao IN ('FIN_BAIXA','CAIXA_ABERTO','CAIXA_FECHADO')")) >= 3)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
