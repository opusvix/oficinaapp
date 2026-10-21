"""Prova da Fase 6: fluxo completo da OS, técnico -> cliente -> técnico -> cliente.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db. Fotos gravadas em
static/uploads/os/ pelo teste são apagadas no fim.
    python scripts/teste_fase6_fluxo.py
Sai com código 1 se algum caso falhar.
"""
import base64
import io
import os
import re
import struct
import sys
import tempfile
import zlib
from pathlib import Path

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402

app = create_app()
falhas = []
fotos_criadas = []


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


def png(largura=520, altura=180):
    """PNG válido sem biblioteca, do tamanho do quadro de assinatura (rabisco em tela branca)."""
    linhas = b"".join(b"\x00" + bytes(0 if (x * 7 + y * 13) % 29 == 0 else 255 for x in range(largura))
                      for y in range(altura))
    def bloco(tipo, dado):
        return struct.pack(">I", len(dado)) + tipo + dado + struct.pack(">I", zlib.crc32(tipo + dado) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 0, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas)) + bloco(b"IEND", b""))


ASSINATURA = "data:image/png;base64," + base64.b64encode(png()).decode()

# ── Preparação ───────────────────────────────────────────────────────────────
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
sql("UPDATE usuario SET precisa_trocar_senha = 0")
tec = sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
          "VALUES ('Tec A', 'a@teste.local', ?, 2, 0) RETURNING id", (h,))[0][0]
sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
    "VALUES ('Tec B', 'b@teste.local', ?, 2, 0)", (h,))
cli = sql("INSERT INTO cliente (razao_social) VALUES ('Lanchonete Teste') RETURNING id")[0][0]
peca = sql("INSERT INTO peca (codigo, descricao, preco_venda, estoque_atual) "
           "VALUES ('RES-01', 'Resistência', 85, 10) RETURNING id")[0][0]


def estoque():
    return float(sql("SELECT estoque_atual FROM peca WHERE id = ?", (peca,))[0][0])


def os_(id_os, campo):
    return sql(f"SELECT {campo} FROM ordem_servico WHERE id = ?", (id_os,))[0][0]


t = app.test_client()
t.post("/auth/login", data={"email": "a@teste.local", "senha": "SenhaTecnico2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', t.get("/os/nova").data).group(1).decode()


def post(c, url, **dados):
    return c.post(url, data={**dados, "csrf_token": TK})


def nova_os(desc="Forno não esquenta"):
    post(t, "/os/nova", id_cliente=str(cli), descricao_inicial=desc)
    return sql("SELECT MAX(id) FROM ordem_servico")[0][0]


def foto(id_os, momento):
    r = t.post(f"/os/{id_os}/foto", content_type="multipart/form-data",
               data={"momento": momento, "csrf_token": TK, "foto": (io.BytesIO(png()), "foto.png")})
    caminho = os_(id_os, f"foto_{momento}")
    if caminho:
        fotos_criadas.append(caminho)
    return r


def token(id_os):
    return os_(id_os, "os_token")


pub = app.test_client()   # o cliente: sem login

# ── 1. Abertura, itens, foto ANTES ───────────────────────────────────────────
o1 = nova_os()
chk("técnico abre OS (status aberta, técnico dono)", os_(o1, "status") == "aberta" and os_(o1, "id_tecnico") == tec)
post(t, f"/os/{o1}/item", id_peca=str(peca), descricao="Resistência", quantidade="2", preco_unitario="85")
post(t, f"/os/{o1}/item", descricao="Fio de silicone (fora do estoque)", quantidade="1", preco_unitario="12")
chk("2 itens: 1 do estoque e 1 digitado livre",
    sql("SELECT COUNT(*) FROM item_os WHERE id_os = ?", (o1,))[0][0] == 2)
foto(o1, "antes")
chk("foto ANTES salva", bool(os_(o1, "foto_antes")))

# ── 2. Cliente aprova pelo link ──────────────────────────────────────────────
post(t, f"/os/{o1}/token")
r = pub.get(f"/os/public/{token(o1)}")
chk("link público mostra Aprovar/Recusar", b'value="aprovar"' in r.data and b'value="recusar"' in r.data)
tkp = re.search(rb'name="csrf_token" value="([^"]+)"', r.data).group(1).decode()
pub.post(f"/os/public/{token(o1)}", data={"decisao": "aprovar", "csrf_token": tkp})
chk("aprovado: OS vai pra 'aprovada'", os_(o1, "status") == "aprovada")
chk("aprovar NÃO baixa estoque (peça ainda não foi usada)", estoque() == 10, estoque())

# ── 3. Execução: entregar exige foto DEPOIS, descrição e teste ──────────────
r = post(t, f"/os/{o1}/entregar")
chk("pedir entrega antes da execução é recusado", os_(o1, "entrega_solicitada_em") is None)
foto(o1, "depois")
post(t, f"/os/{o1}/execucao", descricao_execucao="Troquei a resistência e testei 30 min",
     testado_funcionamento="1")
chk("execução registrada: em_andamento e testado", os_(o1, "status") == "em_andamento"
    and os_(o1, "testado_funcionamento") == 1)
token_aprovacao = token(o1)
post(t, f"/os/{o1}/entregar")
chk("técnico pede validação: NÃO marca entregue sozinho",
    os_(o1, "status") == "em_andamento" and os_(o1, "entrega_solicitada_em") is not None)
chk("pedido de entrega gera link novo", token(o1) != token_aprovacao)

# ── 4. Cliente confere, assina e confirma ENTREGUE ───────────────────────────
r = pub.get(f"/os/public/{token(o1)}")
chk("link mostra o serviço e o quadro de assinatura",
    "Troquei a resistência".encode() in r.data and b"assinaturaQuadro" in r.data)
tkp = re.search(rb'name="csrf_token" value="([^"]+)"', r.data).group(1).decode()
pub.post(f"/os/public/{token(o1)}", data={"decisao": "entregue", "assinatura": "", "csrf_token": tkp})
chk("sem assinatura não fecha", os_(o1, "status") == "em_andamento")
falsa = "data:image/svg+xml;base64," + base64.b64encode(b"<svg onload=alert(1)>").decode()
pub.post(f"/os/public/{token(o1)}", data={"decisao": "entregue", "assinatura": falsa, "csrf_token": tkp})
chk("assinatura que não é PNG (SVG com script) é recusada", os_(o1, "status") == "em_andamento")
pub.post(f"/os/public/{token(o1)}", data={"decisao": "entregue", "assinatura": ASSINATURA, "csrf_token": tkp})
chk("assinou: OS ENTREGUE com data e assinatura",
    os_(o1, "status") == "entregue" and os_(o1, "data_entrega") and os_(o1, "assinatura_cliente") == ASSINATURA)
chk("entrega baixa só a peça do estoque (10 - 2 = 8)", estoque() == 8, estoque())
mov = sql("SELECT tipo, quantidade, origem_tipo, id_origem FROM movimento_estoque WHERE id_peca = ?", (peca,))
chk("movimento SAIDA com origem na OS", len(mov) == 1 and tuple(mov[0]) == ("SAIDA", 2, "OS", o1), [tuple(m) for m in mov])
r = pub.post(f"/os/public/{token(o1)}", data={"decisao": "entregue", "assinatura": ASSINATURA, "csrf_token": tkp})
chk("confirmar de novo: 400 e o estoque não baixa duas vezes", r.status_code == 400 and estoque() == 8,
    f"{r.status_code} {estoque()}")
chk("auditoria registra a entrega pelo cliente",
    len(sql("SELECT 1 FROM logs_acesso WHERE acao = 'OS_ENTREGUE_CLIENTE'")) == 1)

# ── 5. Mexer na execução depois do pedido cancela o pedido ───────────────────
o2 = nova_os("Chapa não aquece")
post(t, f"/os/{o2}/token")
pub.post(f"/os/public/{token(o2)}", data={"decisao": "aprovar", "csrf_token": tkp})
foto(o2, "depois")
post(t, f"/os/{o2}/execucao", descricao_execucao="Troquei o termostato", testado_funcionamento="1")
post(t, f"/os/{o2}/entregar")
post(t, f"/os/{o2}/execucao", descricao_execucao="Troquei o termostato e o cabo", testado_funcionamento="1")
chk("editar a execução zera o pedido de entrega", os_(o2, "entrega_solicitada_em") is None)
r = pub.post(f"/os/public/{token(o2)}", data={"decisao": "entregue", "assinatura": ASSINATURA, "csrf_token": tkp})
chk("cliente não confirma versão que mudou (400)", r.status_code == 400 and os_(o2, "status") == "em_andamento")

# ── 6. Recusa: sem baixa, só deslocamento ────────────────────────────────────
o3 = nova_os("Liquidificador barulhento")
sql("UPDATE ordem_servico SET custo_deslocamento = 40 WHERE id = ?", (o3,))
post(t, f"/os/{o3}/item", id_peca=str(peca), descricao="Resistência", quantidade="3", preco_unitario="85")
post(t, f"/os/{o3}/token")
antes = estoque()
pub.post(f"/os/public/{token(o3)}", data={"decisao": "recusar", "csrf_token": tkp})
r = pub.get(f"/os/public/{token(o3)}")
chk("recusado: OS 'recusada'", os_(o3, "status") == "recusada")
chk("recusa NÃO baixa estoque", estoque() == antes, estoque())
chk("cliente vê 'NÃO foi executado' e o deslocamento", "NÃO foi executado".encode() in r.data and "R$ 40,00".encode() in r.data)

# ── 7. Comprovante / PDF ─────────────────────────────────────────────────────
r = t.get(f"/os/{o1}/comprovante")
chk("comprovante interno abre (dono)", r.status_code == 200 and b"Imprimir / Salvar PDF" in r.data)
chk("comprovante traz assinatura e entrega", ASSINATURA.encode()[:60] in r.data and "Confirmada pelo cliente".encode() in r.data)
chk("comprovante da recusa explica a cobrança", "Cobrança só do deslocamento".encode() in t.get(f"/os/{o3}/comprovante").data)
outro = app.test_client()
outro.post("/auth/login", data={"email": "b@teste.local", "senha": "SenhaTecnico2026"})
chk("comprovante da OS alheia -> 404", outro.get(f"/os/{o1}/comprovante").status_code == 404)
chk("comprovante pelo link do cliente abre", pub.get(f"/os/public/{token(o1)}/comprovante").status_code == 200)
chk("comprovante com token inventado -> 404", pub.get("/os/public/inventado/comprovante").status_code == 404)
chk("comprovante sem script inline fora do nonce", b"onclick" not in r.data)

# ── 8. Cancelar ──────────────────────────────────────────────────────────────
o4 = nova_os("Batedeira sem força")
post(t, f"/os/{o4}/token")
tk4 = token(o4)
post(t, f"/os/{o4}/cancelar")
chk("OS aberta é cancelada (sai da lista)", os_(o4, "D_E_L_E_T") == 1)
chk("cancelar mata o link do cliente", pub.get(f"/os/public/{tk4}").status_code == 404)
post(t, f"/os/{o1}/cancelar")
chk("OS entregue não pode ser cancelada", os_(o1, "D_E_L_E_T") == 0)
r = t.get("/os/?periodo=todos")
chk("listagem tem os 4 slots (ver, editar, PDF, cancelar)",
    all(s in r.data for s in (b"ph-eye", b"ph-pencil-simple", b"ph-file-pdf", b"ph-prohibit")))

# ── 9. Abertura pela tela e filtros (sem <select> nativo) ────────────────────
r = t.get("/clientes/api/busca?q=Lanch")
itens = r.get_json().get("itens", []) if r.status_code == 200 else []
chk("busca de cliente acha pelo nome (técnico pode, abre OS)", any(i["valor"] == cli for i in itens), r.status_code)
r = post(t, "/os/nova", descricao_inicial="sem cliente escolhido")
chk("OS sem cliente -> 422 com 'Escolha o cliente'", r.status_code == 422 and "Escolha o cliente".encode() in r.data,
    r.status_code)
for url in ("/os/nova", "/os/?periodo=todos"):
    html = t.get(url).data
    chk(f"{url} sem <select> nativo", b"<select" not in html)
chk("técnico não vê o campo 'Técnico responsável' (a OS fica com ele)",
    "Técnico responsável".encode() not in t.get("/os/nova").data)
adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
chk("admin vê o campo 'Técnico responsável'", "Técnico responsável".encode() in adm.get("/os/nova").data)
html = adm.get("/os/").data.decode()
chk("listagem abre em 'Mês atual' (chip ligado)", re.search(r'value="mes"\s+class="on"', html) is not None)
chk("rótulo do período é a data ('Abertura'), não 'Período'", ">Abertura<" in html)
chk("lista fechada de 6 presets, na ordem", re.findall(r'name="periodo" value="(\w+)"', html)[:6]
    == ["mes", "mes_passado", "hoje", "7d", "30d", "custom"])
html = adm.get("/os/?periodo=custom").data.decode()
chk("customizado abre PREENCHIDO com o mês atual",
    re.search(r'name="de" value="\d{4}-\d{2}-01"', html) is not None)
chk("Limpar mostra 'Sem filtro de período'", "Sem filtro de período" in adm.get("/os/?periodo=todos").data.decode())
sql("UPDATE ordem_servico SET data_abertura = '2020-01-15 12:00:00' WHERE id = ?", (o1,))
html = adm.get("/os/?periodo=custom&de=2020-01-01&ate=2020-01-31").data.decode()
chk("customizado filtra pela data de abertura", f'data-id="{o1}"' in html and f'data-id="{o3}"' not in html)

# ── 10. Orçamento = soma dos itens ───────────────────────────────────────────
chk("OS entregue: orçamento = soma dos itens (2x85 + 1x12 = 182)", float(os_(o1, "orcamento_valor")) == 182.0,
    os_(o1, "orcamento_valor"))
o5 = nova_os("Fritadeira desarmando")
r = post(t, "/os/nova", id_cliente=str(cli), descricao_inicial="tentando forçar valor", orcamento_valor="9999")
forcada = sql("SELECT MAX(id) FROM ordem_servico")[0][0]
chk("orcamento_valor forjado no form é ignorado (OS nasce com 0)",
    r.status_code == 302 and float(os_(forcada, "orcamento_valor")) == 0.0, f"{r.status_code} {os_(forcada, 'orcamento_valor')}")
chk("OS nasce com orçamento 0 (sem itens)", float(os_(o5, "orcamento_valor")) == 0.0)
post(t, f"/os/{o5}/item", descricao="Mão de obra", quantidade="1", preco_unitario="120")
post(t, f"/os/{o5}/item", descricao="Termostato", quantidade="2", preco_unitario="45,50")
chk("2 itens: orçamento recalculado (120 + 91 = 211)", float(os_(o5, "orcamento_valor")) == 211.0, os_(o5, "orcamento_valor"))
item_termo = sql("SELECT id FROM item_os WHERE id_os = ? AND descricao = 'Termostato'", (o5,))[0][0]
post(t, f"/os/{o5}/item/{item_termo}/remover")
chk("remover item recalcula (211 - 91 = 120)", float(os_(o5, "orcamento_valor")) == 120.0, os_(o5, "orcamento_valor"))
chk("item removido é soft delete", sql("SELECT D_E_L_E_T FROM item_os WHERE id = ?", (item_termo,))[0][0] == 1)
item_o1 = sql("SELECT id FROM item_os WHERE id_os = ? LIMIT 1", (o1,))[0][0]
r = post(t, f"/os/{o5}/item/{item_o1}/remover")
chk("remover item de OUTRA OS pela URL desta -> 404", r.status_code == 404, r.status_code)
r = post(t, f"/os/{o1}/item/{item_o1}/remover")
chk("depois da aprovação o item não sai", sql("SELECT D_E_L_E_T FROM item_os WHERE id = ?", (item_o1,))[0][0] == 0)
sql("UPDATE ordem_servico SET custo_deslocamento = 30 WHERE id = ?", (o5,))
post(t, f"/os/{o5}/token")
r = pub.get(f"/os/public/{token(o5)}")
chk("cliente vê 'Total se aprovar' = itens + deslocamento (R$ 150,00)",
    b"Total se aprovar" in r.data and "R$ 150,00".encode() in r.data)
r = t.get(f"/os/{o3}/comprovante")
chk("comprovante da recusa: total cobrado só o deslocamento", "Total cobrado (só deslocamento)".encode() in r.data)
html = t.get("/os/nova").data
chk("Nova OS sem campo 'Valor do orçamento'", b'name="orcamento_valor"' not in html)

# ── 11. Datas na hora local (banco em UTC) ──────────────────────────────────
sql("UPDATE ordem_servico SET data_abertura = '2026-10-20 01:30:00' WHERE id = ?", (o5,))
html = t.get(f"/os/{o5}").data.decode()
chk("abertura 01:30 UTC aparece 19/10/2026 22:30 (hora de Brasília)", "19/10/2026 22:30" in html)
html = adm.get("/os/?periodo=custom&de=2026-10-19&ate=2026-10-19").data.decode()
chk("filtro do dia 19 local pega a OS aberta 22:30 local (01:30 UTC do dia 20)", f'data-id="{o5}"' in html)
html = adm.get("/os/?periodo=custom&de=2026-10-20&ate=2026-10-20").data.decode()
chk("filtro do dia 20 local NÃO pega essa OS", f'data-id="{o5}"' not in html)

for f in fotos_criadas:
    (RAIZ / "static" / f).unlink(missing_ok=True)
print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
