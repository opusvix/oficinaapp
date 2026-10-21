"""Prova do Controle_de_IP: modos off/monitor/block, prazo, allow e rota pública livre.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db.
    python scripts/teste_seguranca_controle_ip.py
Sai com código 1 se algum caso falhar.
"""
import os
import sys
import tempfile
import time

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ.pop("ADMIN_RESET_SENHA", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402

app = create_app()
falhas = []
RUIM, BOM = "203.0.113.9", "198.51.100.7"


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


def modo(m):
    sql("UPDATE configuracao SET valor = ? WHERE chave = 'ip_protecao_modo'", (m,))


def get(url, ip):
    return app.test_client().get(url, headers={"X-Forwarded-For": ip})


cli = sql("INSERT INTO cliente (razao_social) VALUES ('Bar') RETURNING id")[0][0]
sql("INSERT INTO ordem_servico (id_cliente, patrimonio, os_token, token_expira) "
    "VALUES (?, 'P1', 'tok-publico', '2099-01-01T00:00:00')", (cli,))
sql("INSERT INTO ip_regras (ip, tipo, descricao, quando) VALUES (?, 'block', 'teste', ?)", (RUIM, int(time.time())))

chk("padrão do seed é 'off'", sql("SELECT valor FROM configuracao WHERE chave = 'ip_protecao_modo'")[0][0] == "off")
chk("off: IP da blocklist entra normal", get("/auth/login", RUIM).status_code == 200)

modo("monitor")
chk("monitor: IP da blocklist entra", get("/auth/login", RUIM).status_code == 200)
chk("monitor: registra IP_BLOQUEIO_MONITOR com o IP",
    len(sql("SELECT 1 FROM logs_acesso WHERE acao = 'IP_BLOQUEIO_MONITOR' AND ip = ?", (RUIM,))) >= 1)

modo("block")
chk("block: IP da blocklist -> 403 no login", get("/auth/login", RUIM).status_code == 403)
chk("block: outro IP entra (prova positiva)", get("/auth/login", BOM).status_code == 200)
chk("block: registra IP_BLOQUEADO", len(sql("SELECT 1 FROM logs_acesso WHERE acao = 'IP_BLOQUEADO'")) >= 1)
chk("block: link público do cliente NUNCA é filtrado", get("/os/public/tok-publico", RUIM).status_code == 200)
chk("block: /health livre", get("/health", RUIM).status_code == 200)

sql("UPDATE ip_regras SET expira_em = ? WHERE ip = ?", (int(time.time()) - 60, RUIM))
chk("bloqueio vencido não barra mais", get("/auth/login", RUIM).status_code == 200)

sql("UPDATE ip_regras SET expira_em = NULL WHERE ip = ?", (RUIM,))
sql("INSERT INTO ip_regras (ip, tipo, descricao, quando) VALUES (?, 'allow', 'liberado', ?)", (RUIM, int(time.time())))
chk("allow do mesmo IP vence o block", get("/auth/login", RUIM).status_code == 200)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
