"""Prova do modo demonstração (core/demo.py).

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_modo_demo.py
Sai com código 1 se algum caso falhar.
"""
import os
import re
import sqlite3
import sys
import tempfile

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "demo@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "demo1234"
os.environ["MODO_DEMO"] = "1"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402
from core.demo import modo_demo, credenciais_demo  # noqa: E402

app = create_app()
falhas = []


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def conn():
    return sqlite3.connect(os.environ["FLASK_DATABASE"])


def n(tabela):
    c = conn()
    try:
        return c.execute(f"SELECT COUNT(*) FROM {tabela} WHERE D_E_L_E_T = 0").fetchone()[0]
    finally:
        c.close()


# ── Flags ─────────────────────────────────────────────────────────────────────
chk("modo_demo() True com MODO_DEMO=1", modo_demo() is True)
cred = credenciais_demo()
chk("credenciais_demo() traz e-mail e senha",
    cred and cred["email"] == "demo@teste.local" and cred["senha"] == "demo1234", cred)

os.environ["MODO_DEMO"] = "0"
chk("modo_demo() False com MODO_DEMO=0", modo_demo() is False)
chk("credenciais_demo() None fora da demo", credenciais_demo() is None)
os.environ["MODO_DEMO"] = "1"   # restaura

# ── Boot semeou os dados de exemplo ───────────────────────────────────────────
chk("8 clientes semeados", n("cliente") == 8, n("cliente"))
chk("6 peças semeadas", n("peca") == 6, n("peca"))
chk("12 equipamentos semeados", n("equipamento") == 12, n("equipamento"))

c = conn()
baixo = c.execute("SELECT COUNT(*) FROM peca WHERE estoque_atual < estoque_minimo").fetchone()[0]
trocar = c.execute("SELECT precisa_trocar_senha FROM usuario WHERE email = ?",
                   ("demo@teste.local",)).fetchone()[0]
c.close()
chk("2 peças abaixo do mínimo (acende o painel)", baixo == 2, baixo)
chk("admin de demo NÃO força troca de senha", trocar == 0, trocar)

# ── Tela de login mostra o acesso de demonstração ─────────────────────────────
pagina = app.test_client().get("/auth/login").data.decode()
chk("login tem a caixa de demonstração", "demo-acesso" in pagina)
chk("login mostra o e-mail de demo", "demo@teste.local" in pagina)
chk("login mostra a senha de demo", "demo1234" in pagina)

# ── Login entra direto, sem forçar troca ──────────────────────────────────────
adm = app.test_client()
r = adm.post("/auth/login", data={"email": "demo@teste.local", "senha": "demo1234"})
chk("login de demo vai pra /home (sem troca obrigatória)", r.headers.get("Location", "").endswith("/home"), r.headers.get("Location"))
TK = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get("/home").data).group(1).decode()
chk("banner de demonstração aparece logado", "demo-bar" in adm.get("/home").data.decode())

# ── Guardas: troca de senha e segurança travadas ──────────────────────────────
r = adm.get("/auth/trocar-senha")
chk("GET trocar-senha redireciona (bloqueado na demo)", r.status_code == 302 and r.headers["Location"].endswith("/home"))
r = adm.post("/auth/trocar-senha",
             data={"senha_atual": "demo1234", "senha_nova": "outra1234", "senha_confirma": "outra1234", "csrf_token": TK})
chk("POST trocar-senha não troca (redireciona)", r.status_code == 302)
# a senha segue a mesma: novo login com a original ainda entra
r2 = app.test_client().post("/auth/login", data={"email": "demo@teste.local", "senha": "demo1234"})
chk("senha de demo continua valendo após tentativa de troca", r2.status_code == 302 and r2.headers["Location"].endswith("/home"))

base_seg = {"session_timeout_min": "60", "max_login_tentativas": "5",
            "lockout_janela_min": "15", "ip_protecao_modo": "off", "csrf_token": TK}
r = adm.post("/admin/seguranca/salvar", data={**base_seg, "max_login_tentativas": "1"})
cfg = conn()
tent = cfg.execute("SELECT valor FROM configuracao WHERE chave = 'max_login_tentativas'").fetchone()
cfg.close()
chk("segurança NÃO salva na demo (max_tentativas não virou 1)", tent is None or tent[0] != "1", tent)

# ── Reiniciar demonstração: zera o que o visitante mexeu e devolve o exemplo ───
extra = conn()
extra.execute("INSERT INTO cliente (razao_social, cpf_cnpj) VALUES ('SUJEIRA VISITANTE', '00000000000191')")
extra.commit()
extra.close()
chk("antes do reset: 9 clientes (1 de sujeira)", n("cliente") == 9, n("cliente"))

r = adm.post("/admin/reiniciar-demo", data={"csrf_token": TK})
chk("reset redireciona pra /home", r.status_code == 302 and r.headers["Location"].endswith("/home"))
chk("depois do reset: 8 clientes de novo", n("cliente") == 8, n("cliente"))
chk("depois do reset: 6 peças de novo", n("peca") == 6, n("peca"))

limpo = conn()
sujeira = limpo.execute("SELECT COUNT(*) FROM cliente WHERE razao_social = 'SUJEIRA VISITANTE'").fetchone()[0]
admin_vivo = limpo.execute("SELECT COUNT(*) FROM usuario WHERE email = 'demo@teste.local'").fetchone()[0]
limpo.close()
chk("reset apagou a sujeira do visitante", sujeira == 0, sujeira)
chk("reset preservou o admin de demo", admin_vivo == 1, admin_vivo)

# ── Sanidade: o banco de teste nunca é o oficina.db real ──────────────────────
chk("dev DB nunca é o oficina.db (sanidade)", "oficina.db" not in os.environ["FLASK_DATABASE"])

print()
if falhas:
    print(f"RESULTADO: {len(falhas)} FALHA(S) — " + "; ".join(falhas))
    sys.exit(1)
print("RESULTADO: todos os casos passaram.")
sys.exit(0)
