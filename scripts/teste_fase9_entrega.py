"""Prova da Fase 9: PWA, usuários, guia rápido, Início e preparação da entrega.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_fase9_entrega.py
Sai com código 1 se algum caso falhar.
"""
import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402

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
        linhas = db.execute(q, p).fetchall()
        db.commit()
        return linhas


sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
TEC = sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
          "VALUES ('Tec', 'tec@teste.local', ?, 2, 0) RETURNING id", (h,))[0][0]

adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/home").data).group(1).decode()
tec = app.test_client()
tec.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
TKT = re.search(rb'name="csrf-token" content="([^"]+)"', tec.get("/home").data).group(1).decode()
anon = app.test_client()


def post(c, url, tk=None, **dados):
    return c.post(url, data={**dados, "csrf_token": tk or TK})


# ── 1. PWA ───────────────────────────────────────────────────────────────────
r = anon.get("/manifest.webmanifest")
m = json.loads(r.data) if r.status_code == 200 else {}
chk("manifest público, tipo application/manifest+json", r.status_code == 200 and r.mimetype == "application/manifest+json")
chk("manifest standalone, start_url /home, escopo /", m.get("display") == "standalone" and m.get("start_url") == "/home"
    and m.get("scope") == "/")
chk("manifest sem cache (troca de nome aparece na hora)", "no-cache" in r.headers.get("Cache-Control", ""))
sql("UPDATE configuracao SET valor = 'Oficina do Teste' WHERE chave = 'empresa_nome'")
if not sql("SELECT 1 FROM configuracao WHERE chave = 'empresa_nome'"):
    sql("INSERT INTO configuracao (chave, valor) VALUES ('empresa_nome', 'Oficina do Teste')")
chk("manifest usa o nome da empresa", json.loads(anon.get("/manifest.webmanifest").data)["name"] == "Oficina do Teste")
tamanhos = {}
for ic in m.get("icons", []):
    d = anon.get(ic["src"]).data
    ok_png = d[:8] == b"\x89PNG\r\n\x1a\n"
    w, hh = struct.unpack(">II", d[16:24]) if ok_png else (0, 0)
    tamanhos[ic["src"]] = (ok_png, f"{w}x{hh}" == ic["sizes"])
chk("ícones do manifest existem, são PNG e têm o tamanho declarado", tamanhos and all(a and b for a, b in tamanhos.values()), tamanhos)
chk("tem ícone maskable (Android)", any(i.get("purpose") == "maskable" for i in m.get("icons", [])))
r = anon.get("/service-worker.js")
chk("service worker servido da raiz com Service-Worker-Allowed: /",
    r.status_code == 200 and r.headers.get("Service-Worker-Allowed") == "/" and "javascript" in r.headers["Content-Type"])
chk("service worker sem cache HTTP (atualização chega)", "no-store" in r.headers.get("Cache-Control", ""))
sw = r.data.decode()
chk("SW não guarda POST nem /static/uploads (foto de cliente)", 'req.method !== "GET"' in sw and "/static/uploads/" in sw)
chk("SW: tela vai pra rede, sem rede cai no /offline", 'req.mode === "navigate"' in sw and 'caches.match("/offline")' in sw)
precache = re.findall(r'"(/[^"]+)"', sw[sw.index("PRECACHE"):sw.index("];")])
faltando = [u for u in precache if anon.get(u).status_code != 200]
chk("todo arquivo do PRECACHE existe (senão o install do SW falha inteiro)", not faltando, faltando)
from core.pwa import VERSAO_SW  # noqa: E402
chk("nome do cache do SW = VERSAO_SW do core/pwa.py", f'var CACHE = "{VERSAO_SW}"' in sw)
r = anon.get("/offline")
chk("página offline pública e sem dado de usuário", r.status_code == 200 and "Sem conexão" in r.data.decode()
    and "csrf" not in r.data.decode().lower())
html = adm.get("/home").data.decode()
chk("layout logado tem manifest, apple-touch-icon e registra o SW",
    'rel="manifest"' in html and "apple-touch-icon" in html and "js/pwa.js" in html)
chk("theme-color vem do servidor, sem hex no template", 'name="theme-color" content="#' in html)
chk("login (anônimo) não registra SW", "js/pwa.js" not in anon.get("/auth/login").data.decode())
chk("PWA não abre portão: /home anônimo ainda vai pro login", anon.get("/home").status_code == 302)

# ── 2. Usuários ──────────────────────────────────────────────────────────────
chk("tela de usuários abre pro admin", adm.get("/admin/usuarios").status_code == 200)
chk("menu 'Usuários e Permissões' deixou de ser 'Em breve'", 'href="/admin/usuarios"' in adm.get("/home").data.decode())
chk("técnico não abre usuários -> 403", tec.get("/admin/usuarios").status_code == 403)
r = post(tec, "/admin/usuarios/salvar", tk=TKT, nome="Invasor", email="inv@teste.local", id_perfil="1")
chk("técnico não cria usuário (nem admin) -> 403", r.status_code == 403 and not sql("SELECT 1 FROM usuario WHERE email = 'inv@teste.local'"))
r = post(adm, "/admin/usuarios/salvar", nome="Novo Tec", email="NOVO@Teste.local ", id_perfil="2")
novo = sql("SELECT id, email, precisa_trocar_senha, ativo FROM usuario WHERE email = 'novo@teste.local'")
chk("criado com e-mail minúsculo, ativo e senha provisória", len(novo) == 1 and novo[0][2] == 1 and novo[0][3] == 1)
NOVO = novo[0][0] if novo else 0
senha = re.search(r'id="senhaGerada">([^<]+)<', r.data.decode())
chk("senha provisória na resposta (uma vez) e nunca no cookie de sessão",
    senha is not None and senha.group(1) not in str(r.headers.getlist("Set-Cookie")))
r = post(adm, "/admin/usuarios/salvar", nome="Outro", email="novo@teste.local", id_perfil="2")
chk("e-mail repetido -> 422 com erro no campo", r.status_code == 422 and "Já existe usuário com este e-mail" in r.data.decode())
r = post(adm, "/admin/usuarios/salvar", nome="Cliente Login", email="cli@teste.local", id_perfil="3")
chk("perfil Cliente não ganha login -> 422", r.status_code == 422 and not sql("SELECT 1 FROM usuario WHERE email = 'cli@teste.local'"))
r = post(adm, "/admin/usuarios/salvar", nome="Fantasma", email="fan@teste.local", id_perfil="99")
chk("perfil inexistente -> 422", r.status_code == 422)
r = post(adm, "/admin/usuarios/salvar", nome="Extra", email="extra@teste.local", id_perfil="2", ativo="0",
         precisa_trocar_senha="0")
ex = sql("SELECT ativo, precisa_trocar_senha FROM usuario WHERE email = 'extra@teste.local'")
chk("campos fora da whitelist ignorados (nasce ativo e com troca obrigatória)", ex and tuple(ex[0]) == (1, 1), [tuple(x) for x in ex])
post(adm, "/admin/usuarios/salvar", id=str(NOVO), nome="Novo Tec Editado", email="novo@teste.local", id_perfil="2")
chk("editar nome", sql("SELECT nome FROM usuario WHERE id = ?", (NOVO,))[0][0] == "Novo Tec Editado")
post(adm, "/admin/usuarios/salvar", id="1", nome="Administrador", email="admin@teste.local", id_perfil="2")
chk("admin principal (id 1) não perde o perfil", sql("SELECT id_perfil FROM usuario WHERE id = 1")[0][0] == 1)
post(adm, "/admin/usuarios/1/ativo")
chk("ninguém desativa a si mesmo / o admin principal", sql("SELECT ativo FROM usuario WHERE id = 1")[0][0] == 1)
r = post(adm, f"/admin/usuarios/{TEC}/senha")
nova = re.search(r'id="senhaGerada">([^<]+)<', r.data.decode())
chk("redefinir senha gera provisória e exige troca", nova is not None
    and sql("SELECT precisa_trocar_senha FROM usuario WHERE id = ?", (TEC,))[0][0] == 1)
r = app.test_client().post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
chk("senha antiga para de funcionar", "/home" not in r.headers.get("Location", ""))
chk("sessão aberta do técnico é mandada pra troca", "/auth/trocar-senha" in tec.get("/os/").headers.get("Location", ""))
chk("auditoria registra criação e redefinição, sem senha",
    len(sql("SELECT 1 FROM logs_acesso WHERE acao IN ('USUARIO_CRIADO','SENHA_REDEFINIDA')")) >= 2
    and not sql("SELECT 1 FROM logs_acesso WHERE detalhe LIKE ?", (f"%{nova.group(1) if nova else 'x'}%",)))
r = adm.post("/admin/usuarios/salvar", data={"nome": "Sem Token", "email": "semtk@teste.local", "id_perfil": "2"})
chk("POST sem CSRF não cria usuário", not sql("SELECT 1 FROM usuario WHERE email = 'semtk@teste.local'"))
chk("usuário inexistente -> 404", post(adm, "/admin/usuarios/9999/senha").status_code == 404)

# técnico novo, logado, vira inativo
c_novo = app.test_client()
sql("UPDATE usuario SET senha_hash = ?, precisa_trocar_senha = 0 WHERE id = ?", (h, NOVO))
c_novo.post("/auth/login", data={"email": "novo@teste.local", "senha": "SenhaTecnico2026"})
chk("técnico novo entra", c_novo.get("/home").status_code == 200)
post(adm, f"/admin/usuarios/{NOVO}/ativo")
chk("desativado: a sessão aberta cai na hora", c_novo.get("/home").status_code == 302)
post(adm, f"/admin/usuarios/{NOVO}/ativo")
chk("reativado: entra de novo", sql("SELECT ativo FROM usuario WHERE id = ?", (NOVO,))[0][0] == 1)

# ── 3. Guia rápido e Início ──────────────────────────────────────────────────
r = adm.get("/leiame/").data.decode()
chk("guia rápido no menu (grupo Ajuda)", 'href="/leiame"' in r and "Guia rápido" in r)
chk("admin vê os tópicos de caixa e relatórios", "Abrir e fechar o caixa" in r and "Tirar um relatório" in r)
sql("UPDATE usuario SET precisa_trocar_senha = 0 WHERE id = ?", (TEC,))
tec2 = app.test_client()
sql("UPDATE usuario SET senha_hash = ? WHERE id = ?", (h, TEC))
tec2.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
r = tec2.get("/leiame/").data.decode()
chk("técnico vê OS e agenda, não vê caixa nem relatórios",
    "Abrir uma ordem de serviço" in r and "Marcar visita" in r and "caixa" not in r.lower().split("guia rápido")[-1]
    .split("instalar no celular")[0].replace("caixa de", "") and "Tirar um relatório" not in r)
sql("UPDATE permissoes SET pode_ver = 0 WHERE id_perfil = 2 AND id_modulo = 51")
chk("perfil sem VER no guia -> 403", tec2.get("/leiame/").status_code == 403)
sql("UPDATE permissoes SET pode_ver = 1 WHERE id_perfil = 2 AND id_modulo = 51")
sql("INSERT INTO peca (codigo, descricao, estoque_atual, estoque_minimo) VALUES ('BX1', 'Peça baixa', 1, 3)")
sql("INSERT INTO peca (codigo, descricao, estoque_atual, estoque_minimo) VALUES ('OK1', 'Peça ok', 9, 3)")
r = adm.get("/home").data.decode()
chk("Início do admin: OS, visitas, vencidos, caixa, peças", all(x in r for x in
    ("OS em aberto", "Visitas hoje", "A receber vencido", "Caixa", "Peças no mínimo")))
chk("Início não tem mais o texto do scaffold", "scaffold" not in r.lower() and "Fase 1" not in r)
chk("atalho de peças leva ao filtro 'abaixo do mínimo'", "/estoque/?baixo=1" in r)
r = adm.get("/estoque/?baixo=1").data.decode()
chk("estoque ?baixo=1 mostra só a peça abaixo do mínimo", "BX1" in r and "OK1" not in r)
r = tec2.get("/home").data.decode()
chk("Início do técnico: sem caixa e sem contas", "Caixa" not in r and "A receber" not in r and "OS em aberto" in r)
cli = sql("INSERT INTO cliente (razao_social) VALUES ('C') RETURNING id")[0][0]
for st in ("aberta", "em_andamento", "entregue"):
    sql("INSERT INTO ordem_servico (id_cliente, patrimonio, status) VALUES (?, ?, ?)", (cli, f"P-{st}", st))
r = adm.get("/os/?status=ativas&periodo=todos").data.decode()
chk("OS 'Em aberto (todas)' junta aberta e em andamento, sem entregue",
    "P-aberta" in r and "P-em_andamento" in r and "P-entregue" not in r)

# ── 4. Polimento e entrega ───────────────────────────────────────────────────
tpls = "".join(p.read_text(encoding="utf-8") for p in (RAIZ / "templates").rglob("*.html"))
tpls = re.sub(r"\{#.*?#\}", "", tpls, flags=re.S)   # comentário Jinja que CITA <select> não conta
chk("nenhum <select> nativo nos templates", re.search(r"<select\b", tpls) is None)
chk("nenhum hex #3387E9 nos templates", "#3387E9" not in tpls.upper())
chk("nenhum valor em dinheiro com %.2f cru nos templates", '"%.2f"' not in tpls)
css = (RAIZ / "static/css/components.css").read_text(encoding="utf-8")
chk("label de formulário 13px/600 (Padrao_Formulario)", ".campo label { display: block; font-size: var(--fs-sm); font-weight: 600" in css)
r = adm.get("/clientes/").data.decode()
chk("UF do cliente é SelectBusca", 'id="sbUf"' in r and 'name="uf"' in r)
r = post(adm, "/clientes/salvar", razao_social="Cliente Pela Tela", uf="PR")
chk("cliente salva pela tela (id fora do modelo extra=forbid)", sql("SELECT uf FROM cliente WHERE razao_social = 'Cliente Pela Tela'")
    and sql("SELECT uf FROM cliente WHERE razao_social = 'Cliente Pela Tela'")[0][0] == "PR", r.status_code)
r = post(adm, "/estoque/salvar", codigo="UNI-1", descricao="Peça em litro", unidade="LT")
chk("unidade da peça via SelectBusca salva", sql("SELECT unidade FROM peca WHERE codigo = 'UNI-1'")[0][0] == "LT")
r = post(adm, "/estoque/salvar", codigo="UNI-2", descricao="Peça unidade forjada", unidade="XX")
chk("unidade fora da lista -> recusada", not sql("SELECT 1 FROM peca WHERE codigo = 'UNI-2'"))

# preparar_env em pasta temporária: gera chave, sem BOM, idempotente, não apaga valor existente
import scripts.preparar_env as pe  # noqa: E402
tmp = Path(tempfile.mkdtemp())
pe.ENV, pe.EXEMPLO = tmp / ".env", tmp / ".env.example"
pe.EXEMPLO.write_text("SECRET_KEY=\nFLASK_ENV=development\n# ADMIN_EMAIL=seu@email.com\n", encoding="utf-8")
feito = pe.preparar(perguntar=lambda _: "")
txt = pe.ENV.read_bytes()
chk("preparar_env cria .env, gera SECRET_KEY de 64 e usa e-mail padrão",
    len(re.search(rb"SECRET_KEY=(\w+)", txt).group(1)) == 64 and b"ADMIN_EMAIL=admin@oficina.local" in txt, feito)
chk(".env gravado sem BOM", not txt.startswith(b"\xef\xbb\xbf"))
chave = re.search(rb"SECRET_KEY=(\w+)", txt).group(1)
chk("2ª execução não muda nada", pe.preparar(perguntar=lambda _: "x@y.z") == [] and pe.ENV.read_bytes() == txt)
pe.ENV.write_bytes(b"\xef\xbb\xbfSECRET_KEY=curta\nADMIN_EMAIL=dono@oficina.com\n")
pe.preparar(perguntar=lambda _: "")
txt2 = pe.ENV.read_bytes()
chk(".env antigo com BOM e chave curta: tira o BOM, troca a chave, mantém o e-mail",
    not txt2.startswith(b"\xef\xbb\xbf") and b"dono@oficina.com" in txt2
    and len(re.search(rb"SECRET_KEY=(\w+)", txt2).group(1)) == 64)
def _eof(_):
    raise EOFError
pe.ENV.write_text("SECRET_KEY=" + "a" * 64 + "\n", encoding="utf-8")
pe.preparar(perguntar=_eof)
chk("sem teclado (EOF) usa o e-mail padrão em vez de travar", b"ADMIN_EMAIL=admin@oficina.local" in pe.ENV.read_bytes())

exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
lidas = set(re.findall(r'os\.getenv\("([A-Z_]+)"', "".join(p.read_text(encoding="utf-8")
             for p in list((RAIZ / "core").glob("*.py")) + [RAIZ / "app.py"])))
lidas |= {"FLASK_DATABASE", "FLASK_ENV", "FLASK_DEBUG"}
ativas = set(re.findall(r"^#?\s*([A-Z_]+)=", exemplo, re.M))
chk(".env.example só traz variável que o código lê", ativas <= lidas, ativas - lidas)
dock = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
chk("Dockerfile: gunicorn 1 worker, usuário sem root, healthcheck", '"--workers", "1"' in dock and "USER oficina" in dock
    and "HEALTHCHECK" in dock)
chk(".dockerignore tira .env, banco e uploads", all(x in (RAIZ / ".dockerignore").read_text(encoding="utf-8")
                                                  for x in (".env", "instance/", "static/uploads/")))
req = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
chk("gunicorn no lockfile", "gunicorn==" in req)
for arq in ("LEIA-ME.txt", "MIGRACAO.md", "iniciar.bat"):
    chk(f"{arq} na raiz", (RAIZ / arq).is_file())
chk("iniciar.bat chama preparar_env antes de subir", "preparar_env.py" in (RAIZ / "iniciar.bat").read_text(encoding="ascii"))
chk("app.py só liga debug com FLASK_DEBUG=1", 'debug=os.getenv("FLASK_DEBUG") == "1"' in (RAIZ / "app.py").read_text(encoding="utf-8"))
chk("raiz sem oficina.db solto", not (RAIZ / "oficina.db").exists())

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
