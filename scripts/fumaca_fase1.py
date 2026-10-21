"""Fumaca Fase 1: app sobe, rotas e estaticos respondem."""
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


r = c.get("/health")
chk("health", r.status_code == 200 and r.get_json().get("status") == "ok", str(r.status_code))

r = c.get("/")
chk("raiz -> login", r.status_code == 302 and "/auth/login" in (r.headers.get("Location") or ""),
    str(r.headers.get("Location")))

r = c.get("/auth/login")
chk("tela login", r.status_code == 200, str(r.status_code))
chk("login tem form", b'name="email"' in r.data)
chk("login tem input csrf", b'name="csrf_token"' in r.data)

r = c.get("/home")
chk("home anon -> login", r.status_code == 302 and "/auth/login" in (r.headers.get("Location") or ""),
    str(r.headers.get("Location")))

for arq in (
    "/static/css/tokens.css",
    "/static/css/base.css",
    "/static/css/layout.css",
    "/static/css/components.css",
    "/static/js/main.js",
    "/static/js/selectbusca.js",
    "/static/fonts/fonts.css",
    "/static/fonts/Inter-var-latin.woff2",
    "/static/fonts/Sora-var-latin.woff2",
    "/static/fonts/phosphor/style.css",
    "/static/fonts/phosphor/Phosphor.woff2",
):
    r = c.get(arq)
    chk(arq, r.status_code == 200 and len(r.data) > 0, f"{r.status_code} {len(r.data)}B")

# Banco: tabelas + seed criados?
with app.app_context():
    from core.db import query

    tabs = [row[0] for row in query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("tabelas:", ",".join(tabs))
    for t in ("perfil", "modulo", "permissoes", "usuario", "cliente", "ordem_servico", "peca", "notificacao"):
        chk(f"tabela {t}", t in tabs)
    n_perfis = query("SELECT COUNT(*) c FROM perfil")[0]["c"]
    n_modulos = query("SELECT COUNT(*) c FROM modulo")[0]["c"]
    n_perm = query("SELECT COUNT(*) c FROM permissoes")[0]["c"]
    chk("seed perfis=3", n_perfis == 3, str(n_perfis))
    chk("seed modulos=14", n_modulos == 14, str(n_modulos))
    chk("seed permissoes=20", n_perm == 20, str(n_perm))

# Login real (fluxo completo: POST form -> sessão -> /home)
import os

senha_dev = os.getenv("ADMIN_SENHA_INICIAL", "")
if senha_dev:
    r = c.get("/auth/login")
    r = c.post("/auth/login", data={"email": "admin@oficina.local", "senha": senha_dev},
               follow_redirects=False)
    chk("login POST -> redirect", r.status_code == 302, str(r.status_code))
    r = c.get("/home")
    chk("home autenticada 200", r.status_code == 200, str(r.status_code))
    chk("home mostra nome", b"Administrador" in r.data)
    chk("home tem toggle tema", b"toggleTema" in r.data)
    # senha errada deve voltar 200 com erro
    c2 = app.test_client()
    r = c2.post("/auth/login", data={"email": "admin@oficina.local", "senha": "errada"})
    chk("senha errada -> 200 (re-render)", r.status_code == 200, str(r.status_code))
else:
    print("AVISO: ADMIN_SENHA_INICIAL vazia, teste de login pulado")

# Força bruta: tem que bloquear MESMO com cliente novo a cada tentativa.
# (No bug antigo o contador vivia em session: um cliente novo por tentativa
# nunca chegava a 5 e o bloqueio nunca acontecia.)
from core.auth import MAX_TENTATIVAS, limpar_tentativas

with app.app_context():
    alvo = "forcabruta@oficina.local"
    limpar_tentativas(alvo, "127.0.0.1")
    for i in range(MAX_TENTATIVAS):
        c_bf = app.test_client()  # sessão nova toda vez
        r = c_bf.post("/auth/login", data={"email": alvo, "senha": "errada"})
        chk(f"tentativa {i + 1} -> 200 (re-render)", r.status_code == 200, str(r.status_code))

    c_bf = app.test_client()  # sessão nova de novo: mesmo assim deve estar bloqueado
    r = c_bf.post("/auth/login", data={"email": alvo, "senha": "errada"})
    corpo = r.data.decode("utf-8", "replace")
    chk("bloqueio persiste sem cookie", r.status_code == 200 and "tentativas" in corpo.lower(),
        "sem aviso de bloqueio")
    limpar_tentativas(alvo, "127.0.0.1")

    restam = query(
        "SELECT COUNT(*) c FROM login_tentativas WHERE email = ? OR ip = ?", (alvo, "127.0.0.1")
    )[0]["c"]
    chk("contador limpo no banco", restam == 0, str(restam))

# Notificações (sino): criar -> badge na home -> feed -> marcar lidas -> badge some
if senha_dev:
    import re as _re_n
    from core.menu import notificar
    from core.security import _RATE_LIMITS

    _RATE_LIMITS.clear()  # isolamento: os logins anteriores do teste já gastaram a cota
    c_n = app.test_client()
    r = c_n.post("/auth/login", data={"email": "admin@oficina.local", "senha": senha_dev})
    chk("login p/ teste de notificacao", r.status_code == 302, str(r.status_code))

    with app.app_context():
        from core.db import get_db, query_one

        get_db().execute("DELETE FROM notificacao WHERE titulo LIKE 'FUMACA %'")
        get_db().commit()
        id_admin = query_one("SELECT id FROM usuario WHERE email = 'admin@oficina.local'")["id"]
        notificar(id_admin, "FUMACA aviso de teste", "mensagem de teste", tipo="aviso", rota="/home")

    r = c_n.get("/home")
    corpo = r.data.decode("utf-8", "replace")
    chk("badge do sino aparece na home", "sino-badge" in corpo)

    r = c_n.get("/notificacoes/")
    feed = r.data.decode("utf-8", "replace")
    chk("feed da notificacao 200", r.status_code == 200, str(r.status_code))
    chk("feed mostra a notificacao", "FUMACA aviso de teste" in feed)
    chk("feed nao tem hex da marca", not _re_n.search(r"#3387[eE]9", feed))

    m = _re_n.search(r'name="csrf_token"\s+value="([0-9a-f]{64})"', feed)
    r = c_n.post("/notificacoes/marcar-lidas",
                 data={"csrf_token": m.group(1) if m else "", "destino": "/notificacoes/"})
    chk("marcar lidas -> 302", r.status_code == 302, str(r.status_code))

    r = c_n.get("/home")
    chk("badge some apos marcar lidas", "sino-badge" not in r.data.decode("utf-8", "replace"))

    with app.app_context():
        get_db().execute("DELETE FROM notificacao WHERE titulo LIKE 'FUMACA %'")
        get_db().commit()
else:
    print("AVISO: ADMIN_SENHA_INICIAL vazia, teste de notificacao pulado")

# Prova da casa: nenhum hex da marca fora do tokens.css
import pathlib

raiz = pathlib.Path(".")
for pat in ("templates", "static/css"):
    for p in pathlib.Path(pat).rglob("*"):
        if p.is_file() and p.suffix in (".html", ".css") and p.name != "tokens.css":
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if "#3387e9" in txt.lower():
                chk(f"hex proibido em {p}", False, "#3387E9 encontrado")
print()
print("FALHAS:", falhas if falhas else "nenhuma")
sys.exit(1 if falhas else 0)
