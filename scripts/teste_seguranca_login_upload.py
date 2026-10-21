"""Prova do bloco de segurança: força bruta, auditoria e upload por magic bytes.

Roda em banco DESCARTÁVEL, nunca no instance/oficina.db. As imagens que o teste
grava em static/uploads/ são apagadas no fim.
    python scripts/teste_seguranca_login_upload.py
Sai com código 1 se algum caso falhar.
"""
import io
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["FLASK_DATABASE"] = os.path.join(tempfile.mkdtemp(prefix="oficina_teste_"), "t.db")
os.environ["ADMIN_EMAIL"] = "admin@teste.local"
os.environ["ADMIN_SENHA_INICIAL"] = "SenhaTesteAdmin2026"
os.environ["EMAIL_IGNORAR_BLOQUEIOS"] = "dono@teste.local"
os.environ.pop("ADMIN_RESET_SENHA", None)

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import bcrypt  # noqa: E402
from app import create_app  # noqa: E402

app = create_app()
falhas = []
SENHA = "SenhaCerta2026"
MSG = "Credenciais inválidas.".encode()
BLOQ = "Muitas tentativas".encode()


def chk(rotulo, cond, detalhe=""):
    print(("OK   " if cond else "FAIL ") + rotulo + ("" if cond else f"  <- {detalhe}"))
    if not cond:
        falhas.append(rotulo)


def sql(q, p=()):
    with app.app_context():
        from core.db import get_db
        db = get_db()
        linhas = db.execute(q, p).fetchall()   # ler ANTES do commit (RETURNING)
        db.commit()
        return linhas


h = bcrypt.hashpw(SENHA.encode(), bcrypt.gensalt()).decode()
for email, ativo in (("vitima@teste.local", 1), ("dono@teste.local", 1),
                     ("inativo@teste.local", 0), ("volta@teste.local", 1)):
    sql("INSERT INTO usuario (nome, email, senha_hash, id_perfil, ativo, precisa_trocar_senha) "
        "VALUES (?, ?, ?, 1, ?, 0)", (email, email, h, ativo))
sql("UPDATE usuario SET precisa_trocar_senha = 0")


def tentar(email, senha, ip):
    c = app.test_client()   # sessão nova: o bloqueio não pode depender do cookie
    return c.post("/auth/login", data={"email": email, "senha": senha},
                  headers={"X-Forwarded-For": ip})


# ── Força bruta POR E-MAIL: atacante troca de IP a cada tentativa ────────────
for n in range(5):
    tentar("vitima@teste.local", "errada", f"10.0.1.{n}")
r = tentar("vitima@teste.local", SENHA, "10.0.1.99")
chk("5 falhas no e-mail (IPs diferentes) bloqueiam até a senha certa", BLOQ in r.data and r.status_code == 200,
    r.status_code)

# ── Força bruta POR IP: atacante troca de e-mail a cada tentativa ────────────
for n in range(5):
    tentar(f"chute{n}@teste.local", "errada", "10.0.2.1")
r = tentar("volta@teste.local", SENHA, "10.0.2.1")
chk("5 falhas no IP (e-mails diferentes) bloqueiam o IP", BLOQ in r.data, r.status_code)
r = tentar("volta@teste.local", SENHA, "10.0.2.2")
chk("o mesmo usuário entra de outro IP (prova positiva)", r.status_code == 302, r.status_code)

# ── Acertar zera a conta do e-mail (não a do IP) ─────────────────────────────
for n in range(4):
    tentar("volta@teste.local", "errada", f"10.0.3.{n}")
tentar("volta@teste.local", SENHA, "10.0.3.10")
r = tentar("volta@teste.local", "errada", "10.0.3.20")
chk("4 erros, 1 acerto, 1 erro: não bloqueia (conta do e-mail zerou)", BLOQ not in r.data and MSG in r.data)

# ── Isenção: pula a tranca, mas fica na auditoria ────────────────────────────
for n in range(5):
    tentar("dono@teste.local", "errada", f"10.0.4.{n}")
r = tentar("dono@teste.local", SENHA, "10.0.4.9")
chk("e-mail isento entra mesmo com 5 falhas", r.status_code == 302, r.status_code)
chk("uso da isenção registrado em logs_acesso",
    len(sql("SELECT 1 FROM logs_acesso WHERE acao = 'LOGIN_ISENCAO_LOCKOUT'")) >= 1)

# ── Mensagem única ───────────────────────────────────────────────────────────
r_senha = tentar("inativo@teste.local", "errada", "10.0.5.1")
r_inativo = tentar("inativo@teste.local", SENHA, "10.0.5.2")
r_nao_existe = tentar("ninguem@teste.local", "errada", "10.0.5.3")
chk("senha errada -> 'Credenciais inválidas.'", MSG in r_senha.data)
chk("inativo com senha CERTA -> a mesma mensagem", MSG in r_inativo.data and r_inativo.status_code == 200)
chk("inativo não é revelado", "usuário inativo".encode() not in r_inativo.data.lower())
chk("e-mail inexistente -> a mesma mensagem", MSG in r_nao_existe.data)

# ── Trilha de auditoria ──────────────────────────────────────────────────────
c = app.test_client()
c.post("/auth/login", data={"email": "admin@teste.local", "senha": "SenhaTesteAdmin2026"},
       headers={"X-Forwarded-For": "10.0.6.1"})
tk = re.search(rb'name="csrf-token" content="([^"]+)"', c.get("/auth/trocar-senha").data)
tk = tk.group(1).decode() if tk else ""
c.post("/auth/trocar-senha", data={"senha_atual": "SenhaTesteAdmin2026", "senha_nova": "NovaSenha2026x",
                                   "senha_confirma": "NovaSenha2026x", "csrf_token": tk},
       headers={"X-Forwarded-For": "10.0.6.1"})
c.get("/auth/logout", headers={"X-Forwarded-For": "10.0.6.1"})
acoes = {r[0] for r in sql("SELECT DISTINCT acao FROM logs_acesso")}
for a in ("LOGIN", "LOGIN_FALHA", "LOGIN_BLOQUEADO", "LOGOUT", "TROCA_SENHA"):
    chk(f"logs_acesso registra {a}", a in acoes, sorted(acoes))
chk("logs_acesso grava o IP", len(sql("SELECT 1 FROM logs_acesso WHERE ip = '10.0.6.1'")) >= 2)
detalhes = " ".join((r[0] or "") for r in sql("SELECT detalhe FROM logs_acesso"))
chk("nenhuma senha no detalhe da auditoria",
    all(s not in detalhes for s in (SENHA, "SenhaTesteAdmin2026", "NovaSenha2026x", "errada")))

# ── Upload por magic bytes ───────────────────────────────────────────────────
cli = sql("INSERT INTO cliente (razao_social) VALUES ('Bar Teste') RETURNING id")[0][0]
id_os = sql("INSERT INTO ordem_servico (id_cliente, patrimonio, status) VALUES (?, 'P1', 'aberta') "
            "RETURNING id", (cli,))[0][0]
adm = app.test_client()
adm.post("/auth/login", data={"email": "admin@teste.local", "senha": "NovaSenha2026x"},
         headers={"X-Forwarded-For": "10.0.7.1"})
tk = re.search(rb'name="csrf-token" content="([^"]+)"', adm.get(f"/os/{id_os}").data).group(1).decode()


def enviar(conteudo, nome):
    return adm.post(f"/os/{id_os}/foto",
                    data={"momento": "antes", "csrf_token": tk, "foto": (io.BytesIO(conteudo), nome)},
                    content_type="multipart/form-data", headers={"X-Forwarded-For": "10.0.7.1"})


enviar(b"<?php system($_GET['c']); ?>" + b"\0" * 64, "foto.jpg")
foto = sql("SELECT foto_antes FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
chk("PHP renomeado pra .jpg é recusado", foto is None, foto)

enviar(b"GIF89a" + b"\0" * 64, "foto.png")
foto = sql("SELECT foto_antes FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
chk("GIF com nome .png é recusado", foto is None, foto)

r = enviar(b"\x89PNG\r\n\x1a\n" + b"\0" * (7 * 1024 * 1024), "gigante.png")
chk("corpo acima de 6 MB -> 413 (servidor não aceita o upload inteiro)", r.status_code == 413, r.status_code)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
enviar(PNG, "foto_do_forno.jpg")
foto = sql("SELECT foto_antes FROM ordem_servico WHERE id = ?", (id_os,))[0][0]
chk("PNG de verdade é aceito (prova positiva)", bool(foto), foto)
chk("gravado com a extensão do conteúdo (.png), não do nome (.jpg)", bool(foto) and foto.endswith(".png"), foto)
if foto:
    (RAIZ / "static" / foto).unlink(missing_ok=True)

print(f"\nFALHAS: {len(falhas)}")
sys.exit(1 if falhas else 0)
