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


def _escreve(caminho: Path, linhas: list) -> None:
    caminho.write_text("\r\n".join(linhas) + "\r\n", encoding="ascii")


def _escrever_lancadores(destino: Path) -> None:
    # Launcher SEM janela preta: roda o servidor com pythonw.exe (sem console) e
    # deixa o app abrir o navegador sozinho. O usuário fecha pelo atalho "Fechar".
    _escreve(destino / "OficinaApp.vbs", [
        'Set sh = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'pasta = fso.GetParentFolderName(WScript.ScriptFullName)',
        'sh.CurrentDirectory = pasta',
        r'If Not fso.FolderExists(pasta & "\instance") Then fso.CreateFolder(pasta & "\instance")',
        r'pyw = """" & pasta & "\python\pythonw.exe"""',
        r'sh.Run pyw & " scripts\preparar_env.py", 0, True',
        'sh.Environment("PROCESS")("ABRIR_NAVEGADOR") = "1"',
        'sh.Run pyw & " app.py", 0, False',
        'WScript.Sleep 3500',
        r'senhaTxt = pasta & "\instance\SENHA-INICIAL.txt"',
        'If fso.FileExists(senhaTxt) Then',
        '  If DateDiff("s", fso.GetFile(senhaTxt).DateLastModified, Now) < 90 Then',
        '    sh.Run "notepad.exe """ & senhaTxt & """", 1, False',
        '  End If',
        'End If',
    ])

    # Fechar: encerra quem estiver ouvindo na porta 5000 (o servidor do app).
    _escreve(destino / "Fechar OficinaApp.bat", [
        "@echo off",
        'for /f "tokens=5" %%p in (\'netstat -ano ^| findstr "127.0.0.1:5000" ^| findstr LISTENING\') do taskkill /F /PID %%p >nul 2>&1',
        "echo OficinaApp foi fechado.",
        "timeout /t 2 >nul",
    ])

    # Cria os atalhos (feito em VBS: lida com caminhos e espaços sem dor de cabeca).
    _escreve(destino / "_atalhos.vbs", [
        'Set sh = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'pasta = fso.GetParentFolderName(WScript.ScriptFullName)',
        'desk = sh.SpecialFolders("Desktop")',
        r'Set a = sh.CreateShortcut(desk & "\OficinaApp.lnk")',
        r'a.TargetPath = sh.ExpandEnvironmentStrings("%windir%") & "\System32\wscript.exe"',
        r'a.Arguments = """" & pasta & "\OficinaApp.vbs"""',
        'a.WorkingDirectory = pasta',
        r'a.IconLocation = pasta & "\static\favicon.ico"',
        'a.Save',
        r'Set b = sh.CreateShortcut(desk & "\Fechar OficinaApp.lnk")',
        r'b.TargetPath = pasta & "\Fechar OficinaApp.bat"',
        'b.WorkingDirectory = pasta',
        r'b.IconLocation = pasta & "\static\favicon.ico"',
        'b.Save',
    ])

    _escreve(destino / "Instalar.bat", [
        "@echo off",
        'cd /d "%~dp0"',
        "echo ============================================================",
        "echo  OficinaApp - instalacao",
        "echo ============================================================",
        "echo.",
        'wscript "%~dp0_atalhos.vbs"',
        "echo  Pronto! Na Area de Trabalho foram criados dois atalhos:",
        'echo    - "OficinaApp"         (abre o programa)',
        'echo    - "Fechar OficinaApp"  (encerra o programa)',
        "echo.",
        "echo  Para fixar na Barra de Tarefas: botao DIREITO no atalho OficinaApp,",
        "echo  depois Mostrar mais opcoes e Fixar na barra de tarefas.",
        "echo.",
        "pause",
    ])

    _escreve(destino / "LEIA-ME.txt", [
        "OficinaApp - Gestao para oficinas e assistencias tecnicas",
        "========================================================",
        "",
        "COMO USAR:",
        "",
        "  1. Extraia esta pasta inteira para onde quiser (ex.: C:\\OficinaApp).",
        "  2. De dois cliques em  Instalar.bat  (cria os atalhos na Area de Trabalho).",
        '  3. Abra pelo atalho "OficinaApp". NAO aparece janela preta: o navegador',
        "     abre sozinho em alguns segundos com o sistema.",
        "",
        "PRIMEIRO ACESSO:",
        "  Na primeira vez, abre um bloco de notas com a SENHA INICIAL do",
        "  administrador. Anote e use para entrar (e-mail padrao: admin@oficina.local).",
        "  Troque a senha no primeiro acesso; depois pode apagar esse arquivo.",
        "",
        "PARA FECHAR:",
        '  Use o atalho "Fechar OficinaApp" (ou reinicie o computador). Fechar a aba',
        "  do navegador NAO encerra o programa, que roda por baixo sem janela.",
        "",
        "FIXAR NA BARRA DE TAREFAS (Windows 11):",
        '  Botao DIREITO no atalho "OficinaApp" > Mostrar mais opcoes >',
        "  Fixar na barra de tarefas. (Alternativa: no navegador, clique em",
        '  "Instalar" para ter o OficinaApp como um app separado.)',
        "",
        "OBSERVACOES:",
        "  - Nao precisa instalar Python nem nada: ja vai tudo dentro da pasta.",
        "  - Seus dados ficam no seu computador, na subpasta  instance\\.",
        "  - Se o Windows avisar que nao reconhece o programa, e por nao ser",
        "    assinado digitalmente - pode confiar e mandar executar assim mesmo.",
    ])


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
