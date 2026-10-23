"""Gera dist/OficinaApp-fonte.zip — o código do app pra subir no PythonAnywhere.

    python scripts/empacotar_fonte.py

Diferente do empacotar_windows.py (que embute um Python pro cliente leigo baixar),
aqui vai SÓ o código-fonte: no PythonAnywhere o Python e as dependências são
instalados por lá (virtualenv + pip install -r requirements.txt). Passo a passo:
DEPLOY_PYTHONANYWHERE.md

Não entram: .venv, .git, instance (banco), dist, 00_GENESIS, site, docs, uploads,
testes e o empacotamento Windows — nada de segredo nem de dado real.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
NOME_PASTA = "oficinaapp"   # a pasta que o PythonAnywhere vai receber

PASTAS = ["core", "modules", "templates", "static"]
ARQS_RAIZ = ["app.py", "requirements.txt", ".env.example"]
SCRIPTS = ["schema.sql", "seed.sql", "preparar_env.py", "wsgi_pythonanywhere.py"]


def _copiar(destino: Path) -> None:
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    for pasta in PASTAS:
        shutil.copytree(RAIZ / pasta, destino / pasta, ignore=ign)
    # static/uploads é volume de fotos em runtime; não vai no pacote
    uploads = destino / "static" / "uploads"
    if uploads.exists():
        shutil.rmtree(uploads)
    for arq in ARQS_RAIZ:
        shutil.copy2(RAIZ / arq, destino / arq)
    sdir = destino / "scripts"
    sdir.mkdir()
    for nome in SCRIPTS:
        shutil.copy2(RAIZ / "scripts" / nome, sdir / nome)


def main() -> int:
    destino = DIST / NOME_PASTA
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    _copiar(destino)

    saida = DIST / "OficinaApp-fonte.zip"
    if saida.exists():
        saida.unlink()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arq in destino.rglob("*"):
            if arq.is_file():
                z.write(arq, Path(NOME_PASTA) / arq.relative_to(destino))

    kb = saida.stat().st_size / 1024
    print(f"Pronto: {saida}  ({kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
