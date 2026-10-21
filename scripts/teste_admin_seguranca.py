"""Prova de /admin/seguranca (parâmetros sem redeploy) e do UPSERT em permissões.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_admin_seguranca.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sys
import tempfile
import time

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)
os.environ.pop("EMAIL_IGNORAR_BLOQUEIOS", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        r = db.execute(q, p).fetchall()
        db.commit()
        return r


def cfg(chave):
    r = sql("SELECT valor FROM configuracao WHERE chave = ?", (chave,))
    return r[0][0] if r else None


sql("UPDATE usuario SET precisa_trocar_senha = 0")
h = bcrypt.hashpw(b"SenhaTecnico2026", bcrypt.gensalt()).decode()
sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, precisa_trocar_senha) "
    "VALUES ('Tec', 'tec@teste.local', ?, 2, 0)", (h,))

adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"})
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/home").data).group(1).decode()
tec = app.test_client()
tec.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
TKT = re.search(rb'name="csrf-token" content="([^"]+)"', tec.get("/home").data).group(1).decode()


def salvar(c, tk=None, **dados):
    base = {"session_timeout_min": "60", "max_login_tentativas": "5", "lockout_janela_min": "15", "ip_protecao_modo": "off"}
    return c.post("/admin/seguranca/salvar", data={**base, **dados, "csrf_token": tk or TK})


# ── 1. Tela e menu ───────────────────────────────────────────────────────────
r = adm.get("/admin/seguranca")
chk("tela de segurança abre pro admin", r.status_code == 200 and "Parâmetros de acesso" in r.data.decode())
chk("menu 'Segurança' aparece (módulo 5 semeado)", 'href="/admin/seguranca"' in adm.get("/home").data.decode())
chk("tela mostra os valores atuais do banco", 'name="session_timeout_min"' in r.data.decode() and 'value="60"' in r.data.decode())
chk("controle de IP é SelectBusca, não <select>", 'id="sbModo"' in r.data.decode() and "<select" not in r.data.decode())
chk("técnico não vê segurança -> 403", tec.get("/admin/seguranca").status_code == 403)

# ── 2. Salvar e valer sem redeploy ───────────────────────────────────────────
salvar(adm, session_timeout_min="30", max_login_tentativas="3", lockout_janela_min="20", ip_protecao_modo="monitor")
chk("timeout salvo no banco", cfg("session_timeout_min") == "30")
chk("tentativas salvas", cfg("max_login_tentativas") == "3")
chk("janela salva", cfg("lockout_janela_min") == "20")
chk("modo de IP salvo", cfg("ip_protecao_modo") == "monitor")

# o login respeita o valor novo SEM reiniciar o app
from core.auth import esta_bloqueado, registrar_tentativa  # noqa: E402
with app.test_request_context():
    for _ in range(3):
        registrar_tentativa("vitima@teste.local", "203.0.113.9", sucesso=False)
    chk("3 falhas já bloqueiam (limite novo = 3, sem redeploy)", esta_bloqueado("vitima@teste.local", "203.0.113.9"))
    chk("e-mail e IP limpos não são bloqueados", not esta_bloqueado("outro@teste.local", "203.0.113.99"))

from core.security import timeout_sessao_min  # noqa: E402
with app.test_request_context():
    chk("timeout_sessao_min lê o valor novo (30)", timeout_sessao_min() == 30)

# timeout 0 desliga a expiração
salvar(adm, session_timeout_min="0")
with app.test_request_context():
    chk("timeout 0 salvo e desliga a expiração", cfg("session_timeout_min") == "0" and timeout_sessao_min() == 0)

# ── 3. Validação e mass assignment ───────────────────────────────────────────
# baseline conhecido: todos os campos num valor sabido
salvar(adm, session_timeout_min="60", max_login_tentativas="5", lockout_janela_min="15", ip_protecao_modo="off")
chk("timeout negativo -> 422", salvar(adm, session_timeout_min="-1").status_code == 422)
chk("timeout acima do teto (1441) -> 422", salvar(adm, session_timeout_min="1441").status_code == 422)
chk("tentativas 0 -> 422", salvar(adm, max_login_tentativas="0").status_code == 422)
chk("janela não-numérica -> 422", salvar(adm, lockout_janela_min="abc").status_code == 422)
chk("modo de IP fora da lista -> 422", salvar(adm, ip_protecao_modo="tudo").status_code == 422)
antes = (cfg("session_timeout_min"), cfg("max_login_tentativas"))
chk("valor inválido não grava nada (baseline intacto 60/5)", antes == ("60", "5"), antes)
# campo fora da whitelist: ignorado no servidor (Padrao_Mass_Assignment), não cria chave nova
salvar(adm, session_timeout_min="45", campo_extra="xpto")
chk("campo extra é ignorado: os 4 campos salvam e nada de 'campo_extra' no banco",
    cfg("session_timeout_min") == "45" and cfg("campo_extra") is None)
r = tec.post("/admin/seguranca/salvar", data={"session_timeout_min": "999", "max_login_tentativas": "9",
                                              "lockout_janela_min": "9", "ip_protecao_modo": "off", "csrf_token": TKT})
chk("técnico não salva segurança -> 403", r.status_code == 403)
chk("salvamento do técnico não mexeu no banco (timeout segue 45)", cfg("session_timeout_min") == "45")
n = cfg("session_timeout_min")
adm.post("/admin/seguranca/salvar", data={"session_timeout_min": "77", "max_login_tentativas": "5",
                                          "lockout_janela_min": "15", "ip_protecao_modo": "off"})
chk("POST sem CSRF não altera", cfg("session_timeout_min") == n)
chk("auditoria registra a alteração", len(sql("SELECT 1 FROM logs_acesso WHERE acao = 'SEGURANCA_ALTERADA'")) >= 1)
chk("auditoria não guarda valor que não é de segurança (só os 4 campos)",
    not sql("SELECT 1 FROM logs_acesso WHERE acao = 'SEGURANCA_ALTERADA' AND detalhe LIKE '%senha%'"))

# ── 4. Permissões por UPSERT: nunca DELETE físico (Nunca_DELETE_Fisico) ──────
# estado inicial do técnico (perfil 2): sabe quantas permissões tem
def perm_rows(perfil):
    return sql("SELECT id_modulo, pode_ver, pode_editar, D_E_L_E_T FROM permissoes WHERE id_perfil = ? ORDER BY id_modulo", (perfil,))

antes_rows = {r[0]: (r[1], r[2]) for r in perm_rows(2)}
antes_ids = sql("SELECT id FROM permissoes WHERE id_perfil = 2 ORDER BY id")
# módulos do grupo do técnico pra montar o POST (todos desmarcados = tira tudo que der)
mods = sql("SELECT id, chave FROM modulo WHERE D_E_L_E_T = 0")
# salva a matriz do técnico com SÓ 'clientes' marcado VER
form = {"csrf_token": TK}
id_clientes = [m[0] for m in mods if m[1] == "clientes"][0]
form[f"ver_{id_clientes}"] = "1"
adm.post("/admin/perfis/2/permissoes", data=form)
depois_rows = perm_rows(2)
depois_ids = sql("SELECT id FROM permissoes WHERE id_perfil = 2 ORDER BY id")
chk("nenhuma linha de permissão foi apagada (id continua existindo)",
    {r[0] for r in antes_ids} <= {r[0] for r in depois_ids}, (len(antes_ids), len(depois_ids)))
chk("módulos desmarcados viraram pode_ver=0 (não sumiram)",
    all(r[3] == 0 for r in depois_rows) and any(r[1] == 0 and r[2] == 0 for r in depois_rows))
cli_row = [r for r in depois_rows if r[0] == id_clientes][0]
chk("clientes marcado ficou pode_ver=1", cli_row[1] == 1)
# técnico agora só vê clientes
tec2 = app.test_client()
sql("UPDATE usuario SET senha_hash = ? WHERE email = 'tec@teste.local'", (h,))
tec2.post("/auth/login", data={"email": "tec@teste.local", "senha": "SenhaTecnico2026"})
chk("técnico perdeu OS (desmarcada) -> 403", tec2.get("/os/").status_code == 403)
chk("técnico mantém clientes (marcada) -> 200", tec2.get("/clientes/").status_code == 200)
# remarca OS: a linha que estava 0/0 volta a 1, mesmo id (UPSERT)
form2 = {"csrf_token": TK, f"ver_{id_clientes}": "1"}
id_os = [m[0] for m in mods if m[1] == "os"][0]
form2[f"ver_{id_os}"] = "1"
adm.post("/admin/perfis/2/permissoes", data=form2)
os_rows = [r for r in perm_rows(2) if r[0] == id_os]
chk("remarcar OS reusa a MESMA linha (UPSERT, não nova)", len(os_rows) == 1 and os_rows[0][1] == 1)

# admin blindado: perfil 1 não perde auth/perfis nem salvando a matriz vazia
adm.post("/admin/perfis/1/permissoes", data={"csrf_token": TK})
auth_adm = sql("SELECT pode_ver FROM permissoes p JOIN modulo m ON m.id=p.id_modulo WHERE p.id_perfil=1 AND m.chave='auth'")
chk("admin mantém 'auth' mesmo salvando matriz vazia (blindagem)", auth_adm and auth_adm[0][0] == 1)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
