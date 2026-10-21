"""Fumaça do fluxo completo (Fase 9): o dia de uma oficina, só por HTTP, como as pessoas usam.

admin cria o técnico -> técnico troca a senha provisória -> admin cadastra cliente e
peça -> técnico abre OS, foto ANTES, peças -> link -> cliente aprova -> admin agenda a
visita -> técnico executa, foto DEPOIS, pede validação -> cliente assina ENTREGUE ->
comprovante (PDF por impressão) -> recebível nasceu -> caixa recebe em dinheiro ->
recibo -> relatórios e Início refletem tudo.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_fluxo_completo.py
Sai com código 1 se algum passo falhar.
"""
import base64
import io
import os
import re
import struct
import sys
import tempfile
import zlib
from datetime import timedelta
from pathlib import Path

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "dono@oficina.teste"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaDonoInicial2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import create_app  # noqa: E402
from core.tempo import hoje_local  # noqa: E402

app = create_app()
falhas = []
fotos_criadas = []
HOJE = hoje_local()


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def sql(q, p=()):
    with app.app_context():
        from core.db import get_db
        return get_db().execute(q, p).fetchall()


def png(larg=520, alt=180):
    linhas = b"".join(b"\x00" + bytes(0 if (x * 7 + y * 13) % 29 == 0 else 255 for x in range(larg)) for y in range(alt))
    def b(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + b(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 0, 0, 0, 0))
            + b(b"IDAT", zlib.compress(linhas)) + b(b"IEND", b""))


def tk(c, url="/home"):
    return re.search(rb'name="csrf-token" content="([^"]+)"', c.get(url).data).group(1).decode()


def tk_form(html: bytes):
    return re.search(rb'name="csrf_token" value="([^"]+)"', html).group(1).decode()


def entrar(email, senha):
    c = app.test_client()
    r = c.post("/auth/login", data={"email": email, "senha": senha})
    return c, r


try:
    # ── 1. Dono entra e troca a senha inicial ────────────────────────────────
    dono, r = entrar("dono@oficina.teste", "SenhaDonoInicial2026")
    chk("1º login do dono manda trocar a senha", r.status_code == 302 and "/auth/trocar-senha" in r.headers["Location"])
    chk("sem trocar, qualquer tela volta pra troca", "/auth/trocar-senha" in dono.get("/os/").headers.get("Location", ""))
    t = tk_form(dono.get("/auth/trocar-senha").data)
    dono.post("/auth/trocar-senha", data={"senha_atual": "SenhaDonoInicial2026", "senha_nova": "SenhaDonoInicial2026",
                                          "senha_confirma": "SenhaDonoInicial2026", "csrf_token": t})
    chk("repetir a senha provisória não conta como troca", "/auth/trocar-senha" in dono.get("/os/").headers.get("Location", ""))
    dono.post("/auth/trocar-senha", data={"senha_atual": "SenhaDonoInicial2026", "senha_nova": "DonoNova2026xyz",
                                          "senha_confirma": "DonoNova2026xyz", "csrf_token": t})
    chk("depois da troca, o sistema abre", dono.get("/os/").status_code == 200)
    TD = tk(dono)

    # ── 2. Dono cria o técnico pela tela de usuários ─────────────────────────
    r = dono.post("/admin/usuarios/salvar", data={"nome": "Carlos Técnico", "email": "carlos@oficina.teste",
                                                  "id_perfil": "2", "csrf_token": TD})
    senha_prov = re.search(r'id="senhaGerada">([^<]+)<', r.data.decode())
    chk("usuário criado e senha provisória mostrada uma vez", r.status_code == 200 and senha_prov is not None)
    senha_prov = senha_prov.group(1) if senha_prov else ""
    chk("a lista de usuários não mostra a senha de novo", senha_prov and senha_prov not in dono.get("/admin/usuarios").data.decode())
    chk("log de auditoria não guarda a senha", not sql("SELECT 1 FROM logs_acesso WHERE detalhe LIKE ?", (f"%{senha_prov}%",)))
    tec, r = entrar("carlos@oficina.teste", senha_prov)
    chk("técnico entra com a provisória e cai na troca", "/auth/trocar-senha" in r.headers.get("Location", ""))
    t = tk_form(tec.get("/auth/trocar-senha").data)
    tec.post("/auth/trocar-senha", data={"senha_atual": senha_prov, "senha_nova": "CarlosSenha2026",
                                         "senha_confirma": "CarlosSenha2026", "csrf_token": t})
    TT = tk(tec)
    id_tec = sql("SELECT id FROM usuario WHERE email = 'carlos@oficina.teste'")[0][0]

    # ── 3. Cadastros ─────────────────────────────────────────────────────────
    dono.post("/clientes/salvar", data={"razao_social": "Padaria Fluxo Ltda", "cpf_cnpj": "11.222.333/0001-81",
                                         "telefone1": "(41) 99999-0000", "logradouro": "Rua das Flores", "numero": "100",
                                         "bairro": "Centro", "cidade": "Curitiba", "uf": "PR", "csrf_token": TD})
    cli = sql("SELECT id FROM cliente WHERE razao_social = 'Padaria Fluxo Ltda'")
    chk("cliente cadastrado pela tela", len(cli) == 1)
    cli = cli[0][0] if cli else 0
    dono.post("/estoque/salvar", data={"codigo": "RES-FLX", "descricao": "Resistência do fluxo", "unidade": "UN",
                                        "preco_custo": "40", "preco_venda": "90", "estoque_atual": "5",
                                        "estoque_minimo": "4", "csrf_token": TD})
    peca = sql("SELECT id FROM peca WHERE codigo = 'RES-FLX'")
    chk("peça cadastrada pela tela", len(peca) == 1)
    peca = peca[0][0] if peca else 0

    # ── 4. Técnico abre a OS, foto ANTES, peças, link ────────────────────────
    tec.post("/os/nova", data={"id_cliente": str(cli), "descricao_inicial": "Forno não aquece", "csrf_token": TT})
    o = sql("SELECT id, id_tecnico, patrimonio FROM ordem_servico ORDER BY id DESC LIMIT 1")[0]
    id_os = o[0]
    chk("OS aberta pelo técnico é dele e ganha patrimônio ESG", o[1] == id_tec and o[2] == f"ESG{id_os}", tuple(o))
    tec.post(f"/os/{id_os}/foto", content_type="multipart/form-data",
             data={"momento": "antes", "csrf_token": TT, "foto": (io.BytesIO(png()), "antes.png")})
    f_antes = sql("SELECT foto_antes FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
    if f_antes:
        fotos_criadas.append(f_antes)
    chk("foto ANTES gravada", bool(f_antes))
    tec.post(f"/os/{id_os}/item", data={"id_peca": str(peca), "descricao": "Resistência do fluxo", "quantidade": "2",
                                        "preco_unitario": "90", "csrf_token": TT})
    tec.post(f"/os/{id_os}/item", data={"descricao": "Mão de obra", "quantidade": "1", "preco_unitario": "120", "csrf_token": TT})
    chk("orçamento = soma dos itens (2x90 + 120 = 300)",
        float(sql("SELECT orcamento_valor FROM ordem_servico WHERE id = ?", (id_os,))[0][0]) == 300)
    tec.post(f"/os/{id_os}/token", data={"csrf_token": TT})
    token = sql("SELECT os_token FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
    chk("link do cliente gerado", bool(token))

    # ── 5. Cliente aprova pelo link (sem login) ──────────────────────────────
    pub = app.test_client()
    r = pub.get(f"/os/public/{token}")
    chk("link abre sem login e mostra o total em real (R$ 300,00)", r.status_code == 200 and "R$ 300,00" in r.data.decode())
    pub.post(f"/os/public/{token}", data={"decisao": "aprovar", "csrf_token": tk_form(r.data)})
    chk("orçamento aprovado", sql("SELECT orcamento_status FROM ordem_servico WHERE id = ?", (id_os,))[0][0] == "aprovado")

    # ── 6. Dono agenda a visita ──────────────────────────────────────────────
    amanha = (HOJE + timedelta(days=1)).isoformat()
    dono.post("/agenda/agendar", data={"id_os": str(id_os), "id_tecnico": str(id_tec), "data": amanha, "hora": "09:00",
                                       "duracao": "120", "csrf_token": TD})
    chk("visita agendada pro técnico", len(sql("SELECT 1 FROM agenda WHERE id_os = ? AND status = 'agendado'", (id_os,))) == 1)
    chk("técnico vê a visita na rota do dia", f"OS #{id_os}" in tec.get(f"/agenda/rotas?data={amanha}").data.decode())

    # ── 7. Técnico: foto DEPOIS (vem antes da execução), executa, pede validação ──────────────────────
    tec.post(f"/os/{id_os}/foto", content_type="multipart/form-data",
             data={"momento": "depois", "csrf_token": TT, "foto": (io.BytesIO(png()), "depois.png")})
    f_dep = sql("SELECT foto_depois FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
    if f_dep:
        fotos_criadas.append(f_dep)
    chk("foto DEPOIS gravada", bool(f_dep))
    tec.post(f"/os/{id_os}/execucao", data={"descricao_execucao": "Troquei as resistências e testei 30 min",
                                            "testado_funcionamento": "1", "csrf_token": TT})
    tec.post(f"/os/{id_os}/entregar", data={"csrf_token": TT})
    chk("validação pedida ao cliente", sql("SELECT entrega_solicitada_em FROM ordem_servico WHERE id = ?", (id_os,))[0][0] is not None)
    token = sql("SELECT os_token FROM ordem_servico WHERE id = ?", (id_os,))[0][0]

    # ── 8. Cliente assina ENTREGUE ───────────────────────────────────────────
    r = pub.get(f"/os/public/{token}")
    pub.post(f"/os/public/{token}", data={"decisao": "entregue", "csrf_token": tk_form(r.data),
                                          "assinatura": "data:image/png;base64," + base64.b64encode(png()).decode()})
    st = sql("SELECT status, assinatura_cliente IS NOT NULL FROM ordem_servico WHERE id = ?", (id_os,))[0]
    chk("OS entregue com assinatura", st[0] == "entregue" and st[1] == 1, tuple(st))
    chk("estoque baixou 5 -> 3", float(sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0]) == 3)

    # ── 9. Comprovante (PDF pela impressão) ──────────────────────────────────
    r = tec.get(f"/os/{id_os}/comprovante")
    chk("comprovante abre pro técnico", r.status_code == 200 and "Imprimir" in r.data.decode())
    chk("comprovante abre pelo link do cliente", pub.get(f"/os/public/{token}/comprovante").status_code == 200)

    # ── 10. Financeiro: recebível, caixa, recibo ─────────────────────────────
    rec = sql("SELECT id, valor, status FROM financeiro WHERE id_os = ? AND tipo = 'RECEBER'", (id_os,))
    chk("conta a receber nasceu com orçamento (300)", len(rec) == 1 and float(rec[0][1]) == 300, [tuple(x) for x in rec])
    id_rec = rec[0][0] if rec else 0
    dono.post("/financeiro/caixa/abrir", data={"valor": "50,00", "csrf_token": TD})
    dono.post(f"/financeiro/titulo/{id_rec}/baixar", data={"forma_pagamento": "dinheiro",
                                                         "data_pagamento": HOJE.isoformat(), "csrf_token": TD})
    chk("recebido em dinheiro", sql("SELECT status FROM financeiro WHERE id = ?", (id_rec,))[0][0] == "pago")
    chk("caixa com 50 + 300 na gaveta", "R$ 350,00" in dono.get("/financeiro/caixa").data.decode())
    r = dono.get(f"/financeiro/recibo/{id_rec}")
    chk("recibo com CNPJ formatado", r.status_code == 200 and "11.222.333/0001-81" in r.data.decode())

    # ── 11. Relatórios e Início refletem o dia ───────────────────────────────
    r = dono.get("/relatorios/?aba=clientes").data.decode()
    chk("faturamento por cliente mostra os 300", "Padaria Fluxo Ltda" in r and "R$ 300,00" in r)
    r = dono.get("/relatorios/?aba=pecas").data.decode()
    chk("peças mais usadas mostra a resistência (2)", 'data-codigo="RES-FLX"' in r)
    r = dono.get("/home").data.decode()
    chk("Início do dono: caixa aberto com 350", "Caixa aberto" in r and "R$ 350,00" in r)
    chk("Início do dono: 1 peça no mínimo (3 <= 4)", "Peças no mínimo" in r)
    r = tec.get("/home").data.decode()
    chk("Início do técnico não mostra o caixa", "Caixa" not in r and "OS em aberto" in r)

    # ── 12. Técnico sai: desativado perde o acesso na hora ───────────────────
    t_lista = dono.get("/admin/usuarios").data
    dono.post(f"/admin/usuarios/{id_tec}/ativo", data={"csrf_token": TD})
    r = tec.get("/home")
    chk("técnico desativado perde a sessão aberta", r.status_code == 302 and "/auth/login" in r.headers["Location"])
    _, r = entrar("carlos@oficina.teste", "CarlosSenha2026")
    chk("técnico desativado não entra", r.status_code != 302 or "/home" not in r.headers.get("Location", ""))
    chk("histórico do técnico continua (OS dele intacta)",
        sql("SELECT id_tecnico FROM ordem_servico WHERE id = ?", (id_os,))[0][0] == id_tec)
finally:
    for f in fotos_criadas:
        (RAIZ / "static" / f).unlink(missing_ok=True)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
