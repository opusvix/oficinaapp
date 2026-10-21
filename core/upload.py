"""Upload de imagem validado pelo CONTEÚDO (Padrao_Validacao_de_Input).

A extensão é só o nome que a pessoa deu ao arquivo: um .php renomeado pra
.jpg passava. Aqui quem decide é a assinatura (magic bytes) do começo do
arquivo, e o arquivo é gravado com a extensão do tipo REAL.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from flask import current_app
from werkzeug.datastructures import FileStorage

TAMANHO_MAX_IMAGEM = 5 * 1024 * 1024  # 5 MB
EXTENSOES_ACEITAS = {"jpg", "jpeg", "png", "webp"}
MSG_FORMATO = "Formato não aceito. Use JPG, PNG ou WEBP."
MSG_TAMANHO = "Imagem acima de 5 MB. Reduza e tente de novo."


def tipo_real_imagem(cabeca: bytes) -> Optional[str]:
    """Extensão pelo conteúdo: JPG FF D8 FF, PNG 89 50 4E 47 0D 0A 1A 0A,
    WEBP 'RIFF' .... 'WEBP'. Qualquer outra coisa devolve None."""
    if cabeca[:3] == b"\xff\xd8\xff":
        return "jpg"
    if cabeca[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if cabeca[:4] == b"RIFF" and cabeca[8:12] == b"WEBP":
        return "webp"
    return None


def salvar_imagem(arq: FileStorage, pasta: str) -> tuple[Optional[str], Optional[str]]:
    """Valida e grava em static/uploads/<pasta>/. Devolve (caminho_relativo, erro)."""
    nome = arq.filename or ""
    ext_nome = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if ext_nome not in EXTENSOES_ACEITAS:
        return None, MSG_FORMATO

    arq.stream.seek(0, 2)
    tamanho = arq.stream.tell()
    arq.stream.seek(0)
    if tamanho > TAMANHO_MAX_IMAGEM:
        return None, MSG_TAMANHO

    tipo = tipo_real_imagem(arq.stream.read(12))
    arq.stream.seek(0)
    if tipo is None:
        current_app.logger.warning("UPLOAD_RECUSADO conteudo_nao_e_imagem nome=%s", nome[:80])
        return None, MSG_FORMATO

    destino_rel = f"uploads/{pasta}/{uuid.uuid4().hex[:12]}.{tipo}"
    destino = Path(current_app.root_path) / "static" / destino_rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    arq.save(destino)
    return destino_rel, None


if __name__ == "__main__":
    # Checagem mínima da assinatura (roda sem Flask)
    assert tipo_real_imagem(b"\xff\xd8\xff\xe0" + b"\0" * 8) == "jpg"
    assert tipo_real_imagem(b"\x89PNG\r\n\x1a\n\0\0\0\0") == "png"
    assert tipo_real_imagem(b"RIFF\0\0\0\0WEBP") == "webp"
    assert tipo_real_imagem(b"<?php system($_GET['c']); ?>") is None
    assert tipo_real_imagem(b"") is None
    print("ok")
