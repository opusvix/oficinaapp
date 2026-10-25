"""Prepara o .env no primeiro uso local (chamado pelo iniciar.bat antes do app).

    python scripts/preparar_env.py

O que faz, sem nunca apagar valor que já existe:
1. Sem .env: copia o .env.example.
2. SECRET_KEY vazia ou curta: gera uma nova (o app não sobe sem ela).
3. Sem ADMIN_EMAIL: pergunta o e-mail do administrador (Enter = admin@oficina.local).
   A senha inicial sai sorteada no console na primeira subida ("SENHA INICIAL SORTEADA").
4. Grava em UTF-8 SEM BOM: com BOM a primeira linha vira "\\ufeffSECRET_KEY" e o
   python-dotenv não acha a chave (achado do DIA 4, 19/10/2026).
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENV = RAIZ / ".env"
EXEMPLO = RAIZ / ".env.example"
EMAIL_PADRAO = "admin@oficina.local"


def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig") if p.exists() else ""   # utf-8-sig tira BOM antigo


def _valor(texto: str, chave: str) -> str | None:
    m = re.search(rf"^\s*{chave}\s*=(.*)$", texto, re.M)
    if not m:
        return None
    return m.group(1).split("#", 1)[0].strip().strip('"').strip("'")


def _definir(texto: str, chave: str, valor: str) -> str:
    linha = f"{chave}={valor}"
    if re.search(rf"^\s*{chave}\s*=", texto, re.M):
        return re.sub(rf"^\s*{chave}\s*=.*$", linha, texto, count=1, flags=re.M)
    return texto.rstrip("\n") + "\n" + linha + "\n"


def preparar(perguntar=input) -> list[str]:
    feito = []
    texto = _ler(ENV)
    if not texto:
        texto = _ler(EXEMPLO)
        feito.append(".env criado a partir do .env.example")
    if len(_valor(texto, "SECRET_KEY") or "") < 32:
        texto = _definir(texto, "SECRET_KEY", secrets.token_hex(32))
        feito.append("SECRET_KEY gerada")
    if not _valor(texto, "ADMIN_EMAIL"):
        try:
            email = (perguntar(f"E-mail do administrador [{EMAIL_PADRAO}]: ") or "").strip()
        except (EOFError, RuntimeError, OSError):   # sem teclado/console (pythonw, agendador): usa o padrão
            email = ""
        email = email or EMAIL_PADRAO
        if "@" not in email:
            email = EMAIL_PADRAO
        texto = _definir(texto, "ADMIN_EMAIL", email)
        feito.append(f"administrador: {email} (a senha inicial aparece abaixo, na subida)")
    if feito:
        ENV.write_text(texto, encoding="utf-8", newline="\n")   # sem BOM
    return feito


if __name__ == "__main__":
    for linha in preparar():
        print("[preparar_env]", linha)
    sys.exit(0)
