"""Monta o pacote de instalação do OficinaApp para Windows (sem exigir Python).

Ferramenta de DESENVOLVIMENTO. Gera um .zip autossuficiente: a pessoa extrai,
roda o Instalar.bat (cria o atalho na Área de Trabalho) e usa pelo atalho —
sem instalar Python nem nada. Por dentro vai um Python 3.12 "embeddable" com as
dependências já copiadas do .venv deste projeto.

    python scripts/empacotar_windows.py --embed <python-3.12.10-embed-amd64.zip>

Se --embed não for dado, baixa o embeddable da python.org (precisa de internet).
Saída: dist/OficinaApp-Windows.zip  (e a pasta dist/OficinaApp/ montada).

Por que "--embed" e cópia do .venv: o pacote tem de bater com a MESMA versão
3.12 e plataforma win_amd64 das wheels compiladas (bcrypt, pydantic_core). O
.venv deste projeto já tem tudo instalado e travado no requirements.txt.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
NOME_PASTA = "OficinaApp"
PY_VERSAO = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSAO}/python-{PY_VERSAO}-embed-amd64.zip"

# O que do projeto entra no pacote (nada de .venv, .git, instance, segredos...).
PASTAS_APP = ["core", "modules", "templates", "static"]
ARQS_RAIZ = ["app.py", ".env.example"]
SCRIPTS_RUNTIME = ["schema.sql", "seed.sql", "preparar_env.py"]  # só o essencial de scripts/

# site-packages: copia tudo do .venv MENOS as ferramentas de build (não são runtime).
IGNORAR_PACOTE = {"pip", "setuptools", "pkg_resources", "_distutils_hack", "wheel",
                  "gunicorn"}  # gunicorn é do servidor Linux; no Windows não é usado


def _limpar_dist() -> Path:
    destino = DIST / NOME_PASTA
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    return destino


def _baixar_embed(cache: Path) -> Path:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        return cache
    print(f"Baixando Python embeddable {PY_VERSAO}...")
    urllib.request.urlretrieve(PY_URL, cache)
    return cache


def _montar_python(embed_zip: Path, destino: Path) -> None:
    py_dir = destino / "python"
    py_dir.mkdir()
    with zipfile.ZipFile(embed_zip) as z:
        z.extractall(py_dir)

    # ._pth controla o sys.path. Sem mexer, a pasta do app NÃO entra no path e o
    # "import core" falha. Adiciona ".." (= raiz do pacote, pai de python/) e
    # "Lib\site-packages", e liga o site para os pacotes carregarem normal.
    pth = next(py_dir.glob("python*._pth"))
    pth.write_text(
        "python312.zip\n"
        ".\n"
        "..\n"
        "Lib\\site-packages\n"
        "\n"
        "import site\n",
        encoding="ascii",
    )

    # dependências: copia do .venv deste projeto (mesma versão/plataforma das wheels)
    origem = RAIZ / ".venv" / "Lib" / "site-packages"
    alvo = py_dir / "Lib" / "site-packages"
    alvo.mkdir(parents=True)
    copiados = 0
    for item in sorted(origem.iterdir()):
        base = item.name.split("-")[0].lower()  # "pip-24.0.dist-info" -> "pip"
        if base in IGNORAR_PACOTE or item.name == "__pycache__":
            continue
        if item.is_dir():
            shutil.copytree(item, alvo / item.name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, alvo / item.name)
        copiados += 1
    print(f"  dependências copiadas: {copiados} itens")


def _copiar_app(destino: Path) -> None:
    for pasta in PASTAS_APP:
        shutil.copytree(RAIZ / pasta, destino / pasta,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for arq in ARQS_RAIZ:
        shutil.copy2(RAIZ / arq, destino / arq)
    scripts_dir = destino / "scripts"
    scripts_dir.mkdir()
    for nome in SCRIPTS_RUNTIME:
        shutil.copy2(RAIZ / "scripts" / nome, scripts_dir / nome)


def _escrever_lancadores(destino: Path) -> None:
    # Launcher: prepara .env (1ª vez), abre o navegador sozinho e sobe o servidor.
    (destino / "OficinaApp.bat").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "if not exist instance mkdir instance\r\n"
        "python\\python.exe scripts\\preparar_env.py\r\n"
        "set ABRIR_NAVEGADOR=1\r\n"
        "echo.\r\n"
        "echo  OficinaApp esta iniciando... o navegador abre sozinho em alguns segundos.\r\n"
        "echo  Para FECHAR o programa, feche esta janela preta.\r\n"
        "echo.\r\n"
        "python\\python.exe app.py\r\n",
        encoding="ascii",
    )

    # Instalar.bat: cria o atalho na Área de Trabalho apontando pro launcher.
    # (Roda em qualquer pasta — o programa funciona de onde foi extraído.)
    ps = ("$ws=New-Object -ComObject WScript.Shell;"
          "$lnk=$ws.CreateShortcut([System.IO.Path]::Combine($ws.SpecialFolders('Desktop'),"
          "'OficinaApp.lnk'));"
          "$lnk.TargetPath=Join-Path $env:PASTA 'OficinaApp.bat';"
          "$lnk.WorkingDirectory=$env:PASTA;"
          "$lnk.IconLocation=Join-Path $env:PASTA 'static\\favicon.ico';"
          "$lnk.Save()")
    (destino / "Instalar.bat").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo ============================================================\r\n"
        "echo  OficinaApp - instalacao\r\n"
        "echo ============================================================\r\n"
        "echo.\r\n"
        "set \"PASTA=%~dp0\"\r\n"
        "if \"%PASTA:~-1%\"==\"\\\" set \"PASTA=%PASTA:~0,-1%\"\r\n"
        f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"{ps}\"\r\n"
        "if errorlevel 1 goto erro\r\n"
        "echo  Pronto! Foi criado o atalho \"OficinaApp\" na sua Area de Trabalho.\r\n"
        "echo  De dois cliques nele sempre que quiser abrir o programa.\r\n"
        "echo.\r\n"
        "pause\r\n"
        "exit /b 0\r\n"
        ":erro\r\n"
        "echo  Nao foi possivel criar o atalho. Voce ainda pode abrir pelo OficinaApp.bat.\r\n"
        "echo.\r\n"
        "pause\r\n",
        encoding="ascii",
    )

    (destino / "LEIA-ME.txt").write_text(
        "OficinaApp - Gestao para oficinas e assistencias tecnicas\r\n"
        "========================================================\r\n\r\n"
        "COMO USAR (3 passos):\r\n\r\n"
        "  1. Extraia esta pasta inteira para onde quiser (ex.: C:\\OficinaApp).\r\n"
        "  2. De dois cliques em  Instalar.bat  -> cria o atalho na Area de Trabalho.\r\n"
        "  3. Abra pelo atalho \"OficinaApp\". O navegador abre sozinho no sistema.\r\n\r\n"
        "PRIMEIRO ACESSO:\r\n"
        "  Na primeira vez, a janela preta mostra a SENHA INICIAL do administrador.\r\n"
        "  Anote essa senha para entrar. O e-mail padrao e  admin@oficina.local\r\n\r\n"
        "PARA FECHAR:\r\n"
        "  Feche a janela preta (a do fundo). Para abrir de novo, use o atalho.\r\n\r\n"
        "OBSERVACOES:\r\n"
        "  - Nao precisa instalar Python nem nada: ja vai tudo dentro da pasta.\r\n"
        "  - Seus dados ficam no seu computador, na subpasta  instance\\.\r\n"
        "  - Se o Windows avisar que nao reconhece o programa, e por nao ser\r\n"
        "    assinado digitalmente - pode confiar e mandar executar assim mesmo.\r\n",
        encoding="ascii",
    )


def _zipar(destino: Path) -> Path:
    saida = DIST / "OficinaApp-Windows.zip"
    if saida.exists():
        saida.unlink()
    print("Compactando o .zip (pode levar um minuto)...")
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arq in destino.rglob("*"):
            if arq.is_file():
                z.write(arq, Path(NOME_PASTA) / arq.relative_to(destino))
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description="Empacota o OficinaApp para Windows.")
    ap.add_argument("--embed", type=Path, help="caminho do python-3.12.10-embed-amd64.zip")
    args = ap.parse_args()

    if not (RAIZ / ".venv" / "Lib" / "site-packages").exists():
        sys.exit("ERRO: .venv não encontrado. Rode o iniciar.bat uma vez para criar o ambiente.")

    embed = args.embed or _baixar_embed(DIST / "_cache" / f"python-{PY_VERSAO}-embed-amd64.zip")
    if not embed.exists():
        sys.exit(f"ERRO: embeddable não encontrado em {embed}")

    print(f"Montando pacote em {DIST / NOME_PASTA} ...")
    destino = _limpar_dist()
    _montar_python(embed, destino)
    _copiar_app(destino)
    _escrever_lancadores(destino)
    saida = _zipar(destino)

    mb = saida.stat().st_size / (1024 * 1024)
    print(f"\nPronto: {saida}  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
