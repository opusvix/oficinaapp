"""Fumaca HTTP: bate no servidor vivo em 127.0.0.1:5000 (roda iniciar.bat antes).

    .venv\\Scripts\\python.exe scripts\\fumaca_http.py
"""
import sys
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import re

BASE = "http://127.0.0.1:5000"
EMAIL = "admin@oficina.local"
SENHA = "OficinaDev2026!"

falhas = []


def chk(rotulo, cond, detalhe=""):
    if cond:
        print(f"OK   {rotulo}")
    else:
        print(f"FAIL {rotulo}  <- {detalhe}")
        falhas.append(rotulo)


cj = http.cookiejar.CookieJar()


class SemRedirect(urllib.request.HTTPRedirectHandler):
    """Não segue redirect: devolve o 302 como ele é (guarda cookie mesmo assim)."""

    def redirect_request(self, *a, **k):
        return None


# Um só opener: guarda cookie (sessão) e nunca segue redirect, para o teste
# enxergar o 302 em vez da página de destino.
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), SemRedirect)


def get_sem_redirect(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "fumaca"})
    try:
        r = opener.open(req, timeout=10)
        return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def post_sem_redirect(path, dados):
    corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(
        BASE + path, data=corpo,
        headers={"User-Agent": "fumaca", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        r = opener.open(req, timeout=10)
        return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def get(path, seguir=True):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "fumaca"})
    try:
        r = opener.open(req, timeout=10)
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")
        if e.code in (301, 302, 303, 307, 308) and not seguir:
            return e.code, corpo, dict(e.headers)
        return e.code, corpo, dict(e.headers)


def post(path, dados):
    corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(
        BASE + path, data=corpo, headers={"User-Agent": "fumaca", "Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        r = opener.open(req, timeout=10)
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


# 1. health
try:
    st, body, _ = get("/health")
    chk("health 200", st == 200 and '"ok"' in body, str(st))
except Exception as e:  # servidor fora do ar
    print(f"Servidor nao respondeu em {BASE}: {e}")
    print("Rode iniciar.bat numa janela e de novo esta fumaca.")
    sys.exit(2)

# 2. raiz -> login (302), sem cookie de sessão
st, hdrs = get_sem_redirect("/")
loc = hdrs.get("Location") or ""
chk("raiz -> 302 login", st == 302 and "/auth/login" in loc, f"{st} {loc}")

# 3. tela de login
st, html, hdrs = get("/auth/login")
chk("tela login 200", st == 200, str(st))
chk("login tem form", 'name="email"' in html and 'name="senha"' in html)
chk("login nao vaza stack", "Traceback" not in html and "Werkzeug" not in html)

# 4. login errado volta 200 sem quebrar
st, html, _ = post("/auth/login", {"email": EMAIL, "senha": "SENHA_ERRADA"})
chk("senha errada -> 200", st == 200, str(st))
chk("senha errada nao vaza stack", "Traceback" not in html)

# 5. login certo -> 302
st, html, hdrs = post("/auth/login", {"email": EMAIL, "senha": SENHA})
loc = hdrs.get("Location") or ""
chk("login correto -> 302", st in (302, 303), f"{st} {loc}")

# 6. home autenticada
st, html, hdrs = get("/home")
chk("home 200", st == 200, str(st))
chk("home mostra usuario", "Administrador" in html)
chk("home tem sidebar", 'class="sidebar"' in html)
chk("home tem toggle tema", "toggleTema" in html and "cv-sw" in html)
chk("home tem KPI", "kpi-grid" in html)
chk("home sem traceback", "Traceback" not in html and "jinja2" not in html.lower())

# 6b. CSRF: o POST de um form normal precisa passar (pegou bug de meta/input ausente)
import re as _re

st, html, _ = get("/auth/trocar-senha")
chk("trocar-senha 200", st == 200, str(st))
chk("template tem meta csrf", '<meta name="csrf-token"' in html)
m = _re.search(r'name="csrf_token"\s+value="([0-9a-f]{64})"', html)
chk("form tem input csrf", bool(m), "input csrf_token nao encontrado")
if m:
    token = m.group(1)
    # Com token: volta 200 re-renderizando (senha atual errada), nunca 400
    st, body, _ = post("/auth/trocar-senha", {
        "csrf_token": token, "senha_atual": "errada",
        "senha_nova": "NovaSenha2026!", "senha_confirma": "NovaSenha2026!",
    })
    chk("POST com csrf aceito (senha errada)", st == 200 and "Traceback" not in body, str(st))
    # Sem token: recusa com aviso e volta, não 400 cru
    st, body, hdrs = post("/auth/trocar-senha", {
        "senha_atual": "errada", "senha_nova": "x", "senha_confirma": "y",
    })
    chk("POST sem csrf recusado sem 400", st in (302, 200) and "Bad Request" not in body,
        f"{st} {hdrs.get('Location', '')}")

# 7. home anonimo (cliente novo, sem sessão) -> 302
opener_anon = urllib.request.build_opener(SemRedirect)
try:
    opener_anon.open(urllib.request.Request(BASE + "/home"), timeout=10)
    chk("home anon redireciona", False, "nao redirecionou")
except urllib.error.HTTPError as e:
    chk("home anon -> 302 login", e.code == 302, str(e.code))

# 8. estaticos
for arq in (
    "/static/css/tokens.css",
    "/static/css/components.css",
    "/static/js/main.js",
    "/static/js/selectbusca.js",
    "/static/fonts/phosphor/style.css",
    "/static/fonts/Inter-var-latin.woff2",
):
    st, body, _ = get(arq)
    chk(arq, st == 200 and len(body) > 0, f"{st}")

# 9. headers de seguranca
st, body, hdrs = get("/auth/login")
chk("header X-Frame-Options", hdrs.get("X-Frame-Options") == "DENY", str(hdrs.get("X-Frame-Options")))
chk("header X-Content-Type-Options", hdrs.get("X-Content-Type-Options") == "nosniff",
    str(hdrs.get("X-Content-Type-Options")))
chk("header CSP presente", bool(hdrs.get("Content-Security-Policy")))
chk("header Referrer-Policy", bool(hdrs.get("Referrer-Policy")))

# 10. hex da marca nao aparece em nenhum template servido
st, body, _ = get("/home")
chk("sem hex da marca na tela", not re.search(r"#3387[eE]9", body))

# 11. favicon e pagina de erro amigavel (nao a cru do Werkzeug)
st, body, _ = get("/static/favicon.svg")
chk("favicon 200", st == 200 and "<svg" in body, str(st))
st, hdrs = get_sem_redirect("/favicon.ico")
chk("/favicon.ico redireciona pro svg", st in (301, 302, 308), str(st))
st, body, _ = get("/rota-que-nao-existe")
chk("404 usa erro.html", st == 404 and "Página não encontrada" in body and "Werkzeug" not in body,
    f"{st} {'tem Werkzeug' if 'Werkzeug' in body else ''}")
st, body, _ = get("/static/nao-existe.css")
chk("404 estatico tambem amigavel", st == 404 and "Página não encontrada" in body, str(st))

# 12. Fase 2: menu por permissão, perfis, matriz e sino
st, html, _ = get("/home")
grupos_menu = ("Administração", "Cadastros", "Operacional", "Financeiro", "Relatórios")
chk("menu mostra os 5 grupos", all(g in html for g in grupos_menu),
    str([g for g in grupos_menu if g not in html]))
chk("menu linka /admin/perfis (rota existe)", 'href="/admin/perfis"' in html)
chk("cliente rota existe e linka no menu", 'href="/clientes"' in html)
chk("rota inexistente vira 'em breve', nao link morto",
    'href="/admin/usuarios"' not in html and "em breve" in html)
chk("sino na topbar", "icone sino" in html)
chk("sino aponta pro feed", 'href="/notificacoes/"' in html)
chk("menu sem hex da marca", not re.search(r"#3387[eE]9", html))

# 13. listagem de perfis
st, html, _ = get("/admin/perfis")
chk("/admin/perfis 200", st == 200, str(st))
chk("lista os 3 perfis", all(n in html for n in ("Administrador", "Técnico", "Cliente")))
chk("admin com acesso total (ver 14/14)", "ver 14/14" in html)
chk("perfis nao vaza stack", "Traceback" not in html)

# 14. matriz VER/EDITAR
st, html, _ = get("/admin/perfis/2/permissoes")
chk("matriz tecnico 200", st == 200, str(st))
n_ver = html.count('name="ver_')
n_ed = html.count('name="editar_')
chk("matriz com 14 pares de checkbox", n_ver == 14 and n_ed == 14, f"ver={n_ver} editar={n_ed}")
chk("matriz agrupa por grupo", "Operacional" in html and "Financeiro" in html)
chk("matriz tem csrf", 'name="csrf_token"' in html)

# 15. anônimo não entra no admin (cliente HTTP novo, sem cookie de sessão)
try:
    opener_anon.open(urllib.request.Request(BASE + "/admin/perfis"), timeout=10)
    chk("perfis anon -> 302 login", False, "nao redirecionou")
except urllib.error.HTTPError as e:
    chk("perfis anon -> 302 login", e.code == 302, str(e.code))

# 16. escrita da matriz: EDITAR implica VER, guarda do admin e restauração
def marcadas(pagina):
    """Nomes dos checkboxes que saem marcados no HTML."""
    return set(re.findall(r'name="((?:ver|editar)_\d+)"[^>]*checked', pagina))


def csrf_de(pagina):
    m = re.search(r'name="csrf_token"\s+value="([0-9a-f]{64})"', pagina)
    return m.group(1) if m else ""


def enviar_matriz(id_perfil, caixas, token):
    dados = {"csrf_token": token}
    for nome in caixas:
        dados[nome] = "on"
    return post(f"/admin/perfis/{id_perfil}/permissoes", dados)


# 16a. perfil 3 (Cliente) nasce sem nada: mandar só EDITAR tem que puxar VER
st, html, _ = get("/admin/perfis/3/permissoes")
token3 = csrf_de(html)
orig3 = marcadas(html)
chk("matriz do cliente 200", st == 200, str(st))
chk("cliente sem permissoes no seed", not orig3, str(sorted(orig3)))
st, body, _ = enviar_matriz(3, {"editar_11"}, token3)  # módulo clientes
chk("POST da matriz -> 302", st in (302, 303), str(st))
st, html, _ = get("/admin/perfis/3/permissoes")
depois = marcadas(html)
chk("EDITAR implica VER (gravado pelo servidor)",
    {"ver_11", "editar_11"} <= depois, str(sorted(depois)))
st, body, _ = enviar_matriz(3, orig3, token3)  # restaura (vazio)
st, html, _ = get("/admin/perfis/3/permissoes")
chk("cliente restaurado sem permissoes", marcadas(html) == orig3,
    str(sorted(marcadas(html))))

# 16b. admin não se tranca fora: mesmo sem receber auth/perfis, mantém as duas
st, html, _ = get("/admin/perfis/1/permissoes")
token1 = csrf_de(html)
orig1 = marcadas(html)
chk("matriz do admin 200", st == 200, str(st))
chk("admin nasce com 28 marcadas", len(orig1) == 28, str(len(orig1)))
sem_porta = orig1 - {"ver_1", "editar_1", "ver_2", "editar_2"}
st, body, _ = enviar_matriz(1, sem_porta, token1)
chk("POST matriz admin -> 302", st in (302, 303), str(st))
st, html, _ = get("/admin/perfis/1/permissoes")
depois = marcadas(html)
chk("admin mantem auth+perfis mesmo sem mandar",
    {"ver_1", "editar_1", "ver_2", "editar_2"} <= depois, str(sorted(depois)))
st, body, _ = enviar_matriz(1, orig1, token1)  # restaura
st, html, _ = get("/admin/perfis/1/permissoes")
chk("matriz do admin restaurada", marcadas(html) == orig1, str(len(marcadas(html))))

# 16c. perfil inexistente -> 404 amigável
st, body, _ = get("/admin/perfis/999/permissoes")
chk("perfil inexistente -> 404 amigavel", st == 404 and "Página não encontrada" in body, str(st))

# 17. feed de notificações
st, html, _ = get("/notificacoes/")
chk("/notificacoes 200", st == 200, str(st))
chk("feed vazio amigavel", "Nenhuma notificação" in html)
chk("feed sem hex da marca", not re.search(r"#3387[eE]9", html))

print()
print("FALHAS:", falhas if falhas else "nenhuma")
sys.exit(1 if falhas else 0)
