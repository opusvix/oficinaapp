"""Prova da Fase 8: Agenda + Rotas + Relatórios.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_fase8_agenda_relatorios.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sys
import tempfile
from datetime import timedelta

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402
from core.tempo import agora_utc, hoje_local  # noqa: E402

app = create_app()
falhas = []
HOJE = hoje_local()
D = HOJE + timedelta(days=2)          # dia das visitas (futuro, pra não cair na trava de passado)
D_ISO = D.isoformat()


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


def utc(dias=0, horas=0):
    return (agora_utc() + timedelta(days=dias, hours=horas)).strftime("%Y-%m-%d %H:%M:%S")


# ── Dados ────────────────────────────────────────────────────────────────────
sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
TA = sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
         "VALUES ('Ana Técnica', 'ana@teste.local', ?, 2, 0) RETURNING id", (h,))[0][0]
TB = sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
         "VALUES ('Bruno Técnico', 'bruno@teste.local', ?, 2, 0) RETURNING id", (h,))[0][0]
C1 = sql("INSERT INTO cliente (razao_social, cpf_cnpj, logradouro, numero, bairro, cidade, uf) VALUES "
         "('Padaria Centro', '22333444000181', 'Rua A', '10', 'Centro', 'Curitiba', 'PR') RETURNING id")[0][0]
C2 = sql("INSERT INTO cliente (razao_social, logradouro, numero, bairro, cidade, uf) VALUES "
         "('Mercado Vila', 'Rua B', '20', 'Vila Nova', 'Curitiba', 'PR') RETURNING id")[0][0]


def nova_os(cli, tec=None, status="aberta", pat=None, **extra):
    cols = ["id_cliente", "id_tecnico", "status", "patrimonio"] + list(extra)
    vals = [cli, tec, status, pat or "PAT"] + list(extra.values())
    return sql(f"INSERT INTO ordem_servico ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) RETURNING id",
               tuple(vals))[0][0]


OS1 = nova_os(C1, pat="ESG-A1")               # sem técnico
OS2 = nova_os(C2, pat="ESG-A2")               # sem técnico
OS3 = nova_os(C1, tec=TB, pat="ESG-B3")       # do Bruno
OS4 = nova_os(C2, pat="ESG-A4")               # sem técnico (visita das 21h)
OS5 = nova_os(C1, pat="ESG-A5")               # sem técnico (pra rota com volta de bairro)
OS6 = nova_os(C2, pat="ESG-A6")               # sem técnico (casos de recusa)
OSE = nova_os(C1, tec=TA, status="entregue", pat="ESG-E")

adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/agenda/").data).group(1).decode()
ana = app.test_client()
ana.post("/auth/login", data={"email": "ana@teste.local", "senha": "SenhaTecnico2026"})
TKA = re.search(rb'name="csrf-token" content="([^"]+)"', ana.get("/agenda/").data).group(1).decode()


def agendar(c, tk=None, **dados):
    base = {"id_tecnico": str(TA), "data": D_ISO, "hora": "08:00", "duracao": "60"}
    return c.post("/agenda/agendar", data={**base, **dados, "csrf_token": tk or TK})


def visitas(id_os):
    return sql("SELECT * FROM agenda WHERE id_os = ? AND D_E_L_E_T = 0 ORDER BY id", (id_os,))


# ── 1. Telas ─────────────────────────────────────────────────────────────────
r = adm.get("/agenda/")
chk("agenda semanal abre (admin)", r.status_code == 200 and "Agenda da semana" in r.data.decode())
chk("menu acende 'Agenda e Rotas'", re.search(r'class="[^"]*ativo[^"]*"[^>]*href="/agenda"|href="/agenda"[^>]*class="[^"]*ativo',
                                               r.data.decode()) is not None)
chk("rotas do dia abre", adm.get("/agenda/rotas").status_code == 200)
chk("relatórios abre (admin)", adm.get("/relatorios/").status_code == 200)
chk("OS sem técnico aparece na fila sem visita", "ESG-A1" in r.data.decode() and "Sem técnico" in r.data.decode())

# ── 2. Agendar e atribuir ────────────────────────────────────────────────────
agendar(adm, id_os=str(OS1))
v = visitas(OS1)
chk("visita criada", len(v) == 1 and v[0]["status"] == "agendado", [dict(x) for x in v])
chk("08:00 local gravado como 11:00 UTC", v and v[0]["data_hora_inicio"] == f"{D_ISO} 11:00:00", v and v[0]["data_hora_inicio"])
chk("fim = início + duração", v and v[0]["data_hora_fim"] == f"{D_ISO} 12:00:00", v and v[0]["data_hora_fim"])
chk("OS sem técnico ganha o técnico agendado", sql("SELECT id_tecnico FROM ordem_servico WHERE id = ?", (OS1,))[0][0] == TA)

agendar(adm, id_os=str(OS2), hora="08:30")
chk("visita sobreposta do mesmo técnico é recusada", len(visitas(OS2)) == 0)
chk("recusa não atribui o técnico à OS", sql("SELECT id_tecnico FROM ordem_servico WHERE id = ?", (OS2,))[0][0] is None)
agendar(adm, id_os=str(OS2), hora="09:00")
chk("visita colada (09:00 depois de 08-09) passa", len(visitas(OS2)) == 1)

agendar(adm, id_os=str(OS3), hora="14:00")
chk("OS do Bruno não é agendada para a Ana", len(visitas(OS3)) == 0)
r = agendar(adm, id_os=str(OS3), id_tecnico=str(TB), hora="08:00")
chk("OS do Bruno agendada para ele (no mesmo horário da Ana: técnicos diferentes)", len(visitas(OS3)) == 1)

agendar(adm, id_os=str(OS1), hora="15:00")
chk("OS que já tem visita marcada não ganha outra", len(visitas(OS1)) == 1)
agendar(adm, id_os=str(OS5), data=(HOJE - timedelta(days=1)).isoformat())
chk("agendar no passado é recusado", len(visitas(OS5)) == 0)
agendar(adm, id_os=str(OSE), hora="16:00")
chk("OS entregue não recebe visita", len(visitas(OSE)) == 0)
agendar(adm, id_os=str(OS5), hora="23:00")
chk("hora fora da janela (23:00) é recusada", len(visitas(OS5)) == 0)
agendar(adm, id_os=str(OS6), id_tecnico="1")
chk("técnico que não é técnico (admin id 1) é recusado", len(visitas(OS6)) == 0)
n = len(sql("SELECT 1 FROM agenda"))
adm.post("/agenda/agendar", data={"id_os": str(OS6), "id_tecnico": str(TA), "data": D_ISO, "hora": "16:00", "duracao": "60"})
chk("POST sem token CSRF não grava", len(sql("SELECT 1 FROM agenda")) == n)

agendar(adm, id_os=str(OS4), hora="21:00")
v4 = visitas(OS4)
chk("21:00 local vira 00:00 UTC do dia seguinte", v4 and v4[0]["data_hora_inicio"] == f"{(D + timedelta(days=1)).isoformat()} 00:00:00",
    v4 and v4[0]["data_hora_inicio"])
agendar(adm, id_os=str(OS5), hora="10:00", status="concluido")   # Centro 08, Vila 09, Centro 10
v5 = visitas(OS5)
chk("campo extra no form (status=concluido) é ignorado: visita nasce agendada",
    len(v5) == 1 and v5[0]["status"] == "agendado", [dict(x) for x in v5])

# ── 3. Grade semanal ─────────────────────────────────────────────────────────
html = adm.get(f"/agenda/?semana={D_ISO}").data.decode()
blocos = html.split('<div class="ag-dia ')
dia_d = next((b for b in blocos if D.strftime("%d/%m") in b.split("</div>")[0]), "")
chk("visita das 21h aparece no dia LOCAL (não no dia seguinte)", "21:00" in dia_d and "ESG-A4" in dia_d)
chk("grade mostra 08:00–09:00 da OS1", "08:00–09:00" in dia_d and f"OS #{OS1}" in dia_d)
chk("OS agendada sai da fila sem visita", "data-os=\"%d\"" % OS1 not in html)
html_f = adm.get(f"/agenda/?semana={D_ISO}&tecnico={TB}").data.decode()
chk("filtro de técnico (Bruno) esconde visitas da Ana", "ESG-B3" in html_f and "ESG-A1" not in html_f.split("OS sem visita")[0])
html_c = adm.get(f"/agenda/?semana={D_ISO}&status=cancelado").data.decode()
chk("filtro de situação (cancelados) esconde agendados", "ESG-A1" not in html_c.split("OS sem visita")[0])

# ── 4. Técnico ───────────────────────────────────────────────────────────────
ha = ana.get(f"/agenda/?semana={D_ISO}&tecnico={TB}").data.decode()
chk("técnica vê só a própria agenda (ignora ?tecnico de outro)", "ESG-A1" in ha and "ESG-B3" not in ha)
chk("técnica não vê o filtro de técnico", 'id="fuTecnico"' not in ha)
chk("técnica não vê o botão de agendar", "abrirAgendar" not in ha)
r = agendar(ana, tk=TKA, id_os=str(OS5), hora="16:00")
chk("técnica sem EDITAR não agenda -> 403", r.status_code == 403, r.status_code)
r = ana.post(f"/agenda/{visitas(OS1)[0]['id']}/concluir", data={"csrf_token": TKA})
chk("técnica sem EDITAR não conclui -> 403", r.status_code == 403, r.status_code)
chk("técnico não abre relatórios -> 403", ana.get("/relatorios/").status_code == 403)
hr = ana.get(f"/agenda/rotas?data={D_ISO}&tecnico={TB}").data.decode()
chk("rotas da técnica só com as visitas dela", "ESG-A1" in hr and "ESG-B3" not in hr)

# técnico com EDITAR liberado na matriz: só mexe no que é dele
sql("INSERT OR REPLACE INTO permissoes (id_perfil, id_modulo, pode_ver, pode_editar) VALUES (2, 22, 1, 1)")
ana2 = app.test_client()
ana2.post("/auth/login", data={"email": "ana@teste.local", "senha": "SenhaTecnico2026"})
TKA2 = re.search(rb'name="csrf-token" content="([^"]+)"', ana2.get("/agenda/").data).group(1).decode()
id_v3 = visitas(OS3)[0]["id"]
ana2.post(f"/agenda/{id_v3}/cancelar", data={"csrf_token": TKA2})
chk("técnica com EDITAR não cancela visita do Bruno", visitas(OS3)[0]["status"] == "agendado")
agendar(ana2, tk=TKA2, id_os=str(OS6), id_tecnico=str(TB), hora="16:00")
chk("técnica com EDITAR não agenda para o Bruno", len(visitas(OS6)) == 0)
sql("UPDATE permissoes SET pode_editar = 0 WHERE id_perfil = 2 AND id_modulo = 22")

# ── 5. Concluir / cancelar ───────────────────────────────────────────────────
id_v1 = visitas(OS1)[0]["id"]
adm.post(f"/agenda/{id_v1}/concluir", data={"csrf_token": TK, "semana": D_ISO})
chk("visita concluída", visitas(OS1)[0]["status"] == "concluido")
adm.post(f"/agenda/{id_v1}/cancelar", data={"csrf_token": TK})
chk("visita concluída não volta a cancelada", visitas(OS1)[0]["status"] == "concluido")
id_v2 = visitas(OS2)[0]["id"]
adm.post(f"/agenda/{id_v2}/cancelar", data={"csrf_token": TK})
chk("visita cancelada (registro fica, Nunca_DELETE_Fisico)", visitas(OS2)[0]["status"] == "cancelado")
chk("OS da visita cancelada volta para a fila", 'data-os="%d"' % OS2 in adm.get(f"/agenda/?semana={D_ISO}").data.decode())
agendar(adm, id_os=str(OS2), hora="09:00")
chk("horário da visita cancelada fica livre de novo", len([x for x in visitas(OS2) if x["status"] == "agendado"]) == 1)

# ── 6. Rotas ─────────────────────────────────────────────────────────────────
from modules.agenda import sugerir_rota  # noqa: E402
vs = [{"data_hora_inicio": "2026-01-01 11:00:00", "cidade": "Curitiba", "bairro": "Centro", "id": 1},
      {"data_hora_inicio": "2026-01-01 12:00:00", "cidade": "Curitiba", "bairro": "Vila Nova", "id": 2},
      {"data_hora_inicio": "2026-01-01 13:00:00", "cidade": "Curitiba", "bairro": "centro ", "id": 3}]
rr = sugerir_rota(vs)
chk("rota agrupa o bairro (Centro, Centro, Vila)", [p["id"] for p in rr["paradas"]] == [1, 3, 2], [p["id"] for p in rr["paradas"]])
chk("conta trocas: marcada 2, sugerida 1", (rr["trocas_marcada"], rr["trocas_sugerida"]) == (2, 1))
from modules.agenda import _link_rota  # noqa: E402
lk = _link_rota([{"endereco": "Rua A 10"}, {"endereco": "Rua A 10"}, {"endereco": "Rua B 20"}])
chk("link da rota não repete o mesmo endereço seguido", lk.count("Rua%20A%2010") == 1 and "destination=Rua%20B%2020" in lk, lk)
chk("rota de 1 bairro não avisa", sugerir_rota(vs[:1])["trocas_marcada"] == 0)
hr = adm.get(f"/agenda/rotas?data={D_ISO}&tecnico={TA}").data.decode()
chk("tela de rotas avisa a volta ao bairro", "voltar a um bairro" in hr)
chk("link da rota no mapa com paradas", "maps/dir/?api=1" in hr and "waypoints=" in hr)
chk("endereço montado", "Rua A 10, Centro, Curitiba - PR" in hr)
chk("visita das 21h entra na rota do dia local", "ESG-A4" in hr)
chk("visita concluída não entra na rota (só agendadas)", "ESG-A1" not in hr.split("OS sem visita")[0])
chk("rota de dia sem visita mostra estado vazio",
    "Nenhuma visita agendada" in adm.get(f"/agenda/rotas?data={(D + timedelta(days=30)).isoformat()}").data.decode())

# ── 7. Relatórios ────────────────────────────────────────────────────────────
# Ana: 1 entregue (aberta há 3 dias, aprovada há 2, entregue há 1), 1 recusada; Bruno: OS3 em andamento
sql("UPDATE ordem_servico SET data_abertura = ?, data_aprovacao = ?, data_entrega = ?, orcamento_status = 'aprovado', "
    "orcamento_valor = 200, custo_deslocamento = 50 WHERE id = ?", (utc(-3), utc(-2), utc(-1), OSE))
OSR = nova_os(C2, tec=TA, status="recusada", pat="ESG-R", orcamento_status="recusado")
P1 = sql("INSERT INTO peca (codigo, descricao, unidade) VALUES ('RES-1', 'Resistência 220V', 'UN') RETURNING id")[0][0]
OSE2 = nova_os(C2, tec=TB, status="entregue", pat="ESG-E2", data_entrega=utc(-1), data_abertura=utc(-1, -5),
               data_aprovacao=utc(-1, -4))
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario) VALUES (?, ?, 'Resistência', 2, 30)", (OSE, P1))
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario) VALUES (?, ?, 'Resistência', 3, 30)", (OSE2, P1))
sql("INSERT INTO item_os (id_os, descricao, quantidade, preco_unitario) VALUES (?, 'Mão de obra', 1, 120)", (OSE,))
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario) VALUES (?, ?, 'Resistência', 9, 30)", (OS3, P1))
sql("INSERT INTO item_os (id_os, id_peca, descricao, quantidade, preco_unitario, D_E_L_E_T) VALUES (?, ?, 'Resistência', 7, 30, 1)", (OSE, P1))

r = adm.get("/relatorios/?aba=tecnicos&periodo=todos").data.decode()
linha_ana = re.search(r'<tr data-tecnico="Ana Técnica"([^>]*)>', r)
attrs = dict(re.findall(r'data-(\w+)="([^"]*)"', linha_ana.group(1))) if linha_ana else {}
chk("OS por técnico: Ana com 1 entregue e 1 recusada", attrs.get("entregues") == "1" and attrs.get("recusadas") == "1", attrs)
chk("OS por técnico: aprovação 50% (1 aprovado, 1 recusado)", attrs.get("taxa") == "50", attrs)
chk("OS por técnico: valor entregue = orçamento + deslocamento (250)", "R$ 250,00" in r)
chk("OS sem técnico agrupadas como 'Sem técnico' (OS6)", 'data-tecnico="Sem técnico"' in r)
r = adm.get(f"/relatorios/?aba=tecnicos&periodo=todos&tecnico={TB}").data.decode()
chk("filtro de técnico no relatório", "Bruno Técnico" in r and 'data-tecnico="Ana Técnica"' not in r)
r = adm.get("/relatorios/?aba=tecnicos&periodo=todos&status=recusada").data.decode()
chk("filtro de status no relatório (só recusadas)", 'data-tecnico="Ana Técnica"' in r and 'data-tecnico="Bruno Técnico"' not in r)

r = adm.get("/relatorios/?aba=tempo&periodo=todos").data.decode()
chk("tempo médio Ana: abertura->entrega 2,0 dias, aprovação->entrega 1,0 dias", "2,0 dias" in r and "1,0 dias" in r)
chk("tempo médio Bruno em horas (5h abertura->entrega)", "5,0 h" in r)

r = adm.get("/relatorios/?aba=pecas&periodo=todos").data.decode()
pec = re.search(r'<tr data-codigo="RES-1"([^>]*)>', r)
pattrs = dict(re.findall(r'data-(\w+)="([^"]*)"', pec.group(1))) if pec else {}
chk("peça mais usada soma só OS entregue e item ativo (2 + 3 = 5)", pattrs.get("qtd") == "5.0", pattrs)
chk("peça em 2 OS, valor 150", pattrs.get("n_os") == "2" and pattrs.get("valor") == "150.00", pattrs)
chk("item digitado livre marcado 'Fora do estoque' na coluna Origem", re.search(r'data-descricao="Mão de obra" data-origem="avulso"', r) is not None)
chk("peça vem antes da mão de obra (mais usada primeiro)", r.index("RES-1") < r.index("Mão de obra"))

sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, status, data_pagamento, id_cliente, id_os) "
    "VALUES ('RECEBER', 'OS E', 250, ?, 'pago', ?, ?, ?)", (HOJE.isoformat(), HOJE.isoformat(), C1, OSE))
sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, status, data_pagamento, id_cliente) "
    "VALUES ('RECEBER', 'Avulso', 50, ?, 'pago', ?, ?)", (HOJE.isoformat(), HOJE.isoformat(), C1))
sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, status, id_cliente) "
    "VALUES ('RECEBER', 'Parcela', 30, ?, 'aberto', ?)", (HOJE.isoformat(), C1))
sql("INSERT INTO financeiro (tipo, descricao, valor, data_vencimento, status, data_pagamento, id_cliente) "
    "VALUES ('PAGAR', 'Fornecedor', 999, ?, 'pago', ?, ?)", (HOJE.isoformat(), HOJE.isoformat(), C1))
r = adm.get("/relatorios/?aba=clientes").data.decode()
cl = re.search(r'<tr data-cliente="Padaria Centro"([^>]*)>', r)
cattrs = dict(re.findall(r'data-(\w+)="([^"]*)"', cl.group(1))) if cl else {}
chk("faturamento: recebido 300 (250 + 50, conta a PAGAR fora) no Mês atual", cattrs.get("recebido") == "300.00", cattrs)
chk("faturamento: em aberto hoje 30, 2 títulos, 1 OS", cattrs.get("aberto") == "30.00" and cattrs.get("titulos") == "2"
    and cattrs.get("n_os") == "1", cattrs)
chk("faturamento mostra CNPJ com máscara", "22.333.444/0001-81" in r)
r = adm.get("/relatorios/?aba=clientes&periodo=custom&de=2000-01-01&ate=2000-01-31").data.decode()
chk("período sem dado mostra estado vazio", "Nada neste período" in r and "Padaria Centro" not in r)
chk("relatório não tem card de KPI (Listagens_sem_KPI)", "mg-kpi" not in r)
chk("tabela exportável (TabelaAvancada com prefKey do relatório)", 'data-pref-key="rel_faturamento_cliente"' in r
    and "tabela-avancada.js" in r)
chk("aba inválida cai na primeira", "OS abertas" in adm.get("/relatorios/?aba=xpto&periodo=todos").data.decode())
chk("abas mantêm o período ao trocar", "aba=tempo&amp;periodo=todos" in adm.get("/relatorios/?periodo=todos").data.decode()
    or "periodo=todos&amp;aba=tempo" in adm.get("/relatorios/?periodo=todos").data.decode())

chk("auditoria registra agendar/concluir/cancelar",
    len(sql("SELECT 1 FROM logs_acesso WHERE acao IN ('AGENDA_CRIADA','AGENDA_CONCLUIDA','AGENDA_CANCELADA')")) >= 3)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
