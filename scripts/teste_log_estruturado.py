"""Prova do application log em JSON (Padrao_Logging_Estruturado).

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_log_estruturado.py
Sai com código 1 se algum caso falhar.
"""
import json
import logging
import os
import re
import sys
import tempfile

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402
from core.applog import _JsonFormatter, log_event, redige_email  # noqa: E402

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
        r = db.execute(q, p).fetchall()
        db.commit()
        return r


# Captura as linhas do logger "oficina.app" (os campos já saem redigidos de log_event)
CAP = []


class _Cap(logging.Handler):
    def emit(self, record):
        CAP.append(record)


logging.getLogger("oficina.app").addHandler(_Cap())
FMT = _JsonFormatter()


def eventos(nome=None):
    return [r for r in CAP if nome is None or r.getMessage() == nome]


def ultimo(nome):
    es = eventos(nome)
    return getattr(es[-1], "campos", {}) if es else None


# ── 0. Unidade: redige_email e campos fixos ─────────────────────────────────
chk("redige_email mascara o usuário e mantém o domínio",
    redige_email("joao.silva@exemplo.com") == "j***@exemplo.com")
chk("redige_email acha e-mail no meio do texto",
    redige_email("email=ana@x.co motivo=senha") == "email=a***@x.co motivo=senha")
chk("redige_email não quebra texto sem e-mail", redige_email("titulo=5 forma=pix") == "titulo=5 forma=pix")
with app.test_request_context("/x", method="POST"):
    from flask import g as _g
    _g.request_id = "rid-unit"; _g.user_id = None
    log_event("TESTE_UNIT", campo="v")
u = ultimo("TESTE_UNIT")
chk("log_event preenche path, method e request_id", u and u["path"] == "/x" and u["method"] == "POST"
    and u.get("request_id") == "rid-unit")
linha = FMT.format(eventos("TESTE_UNIT")[-1])
doc = json.loads(linha)
chk("linha é JSON válido com timestamp, level e event",
    doc["event"] == "TESTE_UNIT" and doc["level"] == "INFO" and "T" in doc["timestamp"])
chk("fora de request, campos fixos viram null", (
    log_event("SEM_REQ") or True) and all(ultimo("SEM_REQ")[k] is None for k in ("user_id", "ip", "path", "method")))

# ── Dados ────────────────────────────────────────────────────────────────────
sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
    "VALUES ('Tec', 'tecnico@teste.local', ?, 2, 0)", (h,))

# ── 1. Login ok / falha ─────────────────────────────────────────────────────
adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
ev = ultimo("LOGIN")
chk("LOGIN_OK vira evento com user_id e request_id", ev and ev["user_id"] == 1 and ev.get("request_id"))
chk("LOGIN não vaza e-mail em claro", ev and "admin@teste.local" not in json.dumps(ev) and "a***@teste.local" in json.dumps(ev))

anon = app.test_client()
anon.post("/auth/login", data={"email": "tecnico@teste.local", "senha": "senha-errada"})
ev = ultimo("LOGIN_FALHA")
chk("LOGIN_FALHA é evento", ev is not None)
blob = json.dumps(ev)
chk("LOGIN_FALHA não vaza e-mail nem a senha tentada",
    "tecnico@teste.local" not in blob and "senha-errada" not in blob, blob)
chk("LOGIN_FALHA mantém o domínio redigido pra diagnóstico", "t***@teste.local" in blob)

# ── 2. 403 e CSRF ───────────────────────────────────────────────────────────
tec = app.test_client()
tec.post("/auth/login", data={"email": "tecnico@teste.local", "senha": "SenhaTecnico2026"})
r = tec.get("/admin/seguranca")   # técnico não pode: 403
chk("acesso negado 403 vira evento ACESSO_NEGADO_403", r.status_code == 403 and eventos("ACESSO_NEGADO_403"))
e403 = ultimo("ACESSO_NEGADO_403")
chk("403 registra quem (user_id do técnico), path e method",
    e403 and e403["user_id"] == sql("SELECT id FROM usuario WHERE email='tecnico@teste.local'")[0][0]
    and e403["path"] == "/admin/seguranca" and e403["method"] == "GET")
chk("403 sai com level WARN (não WARNING)", json.loads(FMT.format(eventos("ACESSO_NEGADO_403")[-1]))["level"] == "WARN")

r = adm.post("/admin/seguranca/salvar", data={"session_timeout_min": "30", "max_login_tentativas": "5",
                                              "lockout_janela_min": "15", "ip_protecao_modo": "off"})  # sem csrf_token
chk("POST sem CSRF vira evento CSRF_INVALIDO", eventos("CSRF_INVALIDO"))
chk("CSRF_INVALIDO guarda a rota, não o token", "rota" in (ultimo("CSRF_INVALIDO") or {})
    and "csrf" not in json.dumps(ultimo("CSRF_INVALIDO")).lower())

# ── 3. Mutação crítica (muda parâmetro de segurança) ────────────────────────
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/home").data).group(1).decode()
adm.post("/admin/seguranca/salvar", data={"session_timeout_min": "40", "max_login_tentativas": "5",
                                          "lockout_janela_min": "15", "ip_protecao_modo": "off", "csrf_token": TK})
chk("alteração de segurança vira evento no application log", eventos("SEGURANCA_ALTERADA"))
chk("evento de segurança traz os campos de request (user_id, request_id, path)",
    (lambda e: e and e["user_id"] == 1 and e.get("request_id") and e["path"].startswith("/admin/seguranca"))
    (ultimo("SEGURANCA_ALTERADA")))

# ── 4. Rate limit ───────────────────────────────────────────────────────────
from core.security import rate_limit  # noqa: E402
with app.test_request_context("/x", method="POST"):
    from flask import g
    g.request_id = "rid-teste"
    g.user_id = None
    try:
        for _ in range(3):
            rate_limit(2, 60)(lambda: None)()  # limite 2: a 3ª estoura
    except Exception:
        pass
chk("rate limit estourado vira evento RATE_LIMIT_HIT", eventos("RATE_LIMIT_HIT"))
chk("RATE_LIMIT_HIT tem endpoint e level WARN",
    "endpoint" in (ultimo("RATE_LIMIT_HIT") or {}) and json.loads(FMT.format(eventos("RATE_LIMIT_HIT")[-1]))["level"] == "WARN")

# ── 5. Nenhuma linha vaza senha, token ou e-mail em claro ───────────────────
todas = "\n".join(FMT.format(r) for r in CAP + eventos())
emails_claros = ["tecnico@teste.local", "admin@teste.local", "joao.silva@exemplo.com"]
chk("nenhuma linha vaza senha ou e-mail em claro",
    "senha-errada" not in todas and all(e not in todas for e in emails_claros), todas[:200])
chk("todo e-mail que aparece está redigido (***@)",
    all("***@" in frag for frag in re.findall(r"\S*@\S*", todas)),
    re.findall(r"\S*@\S*", todas))
# cada linha capturada é JSON de uma linha só (sem quebra), com os 8 campos fixos quando em request
amostra = FMT.format(eventos("SEGURANCA_ALTERADA")[-1])
d = json.loads(amostra)
chk("linha tem os campos fixos do padrão", all(k in d for k in
    ("timestamp", "level", "event", "user_id", "ip", "request_id", "path", "method")))
chk("linha é uma única linha (sem \\n no meio)", "\n" not in amostra)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
