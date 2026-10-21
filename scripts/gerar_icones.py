"""Gera os ícones PNG do PWA a partir do logo da ESG (static/img/logo-esg.jpeg).

Ferramenta de DESENVOLVIMENTO: precisa do Pillow, que NÃO está no requirements do
app (como o pip-compile, fica fora do runtime). Instale só pra rodar isto:
    pip install pillow
    python scripts/gerar_icones.py

O logo é colocado centralizado num quadrado preto (letterbox), do mesmo jeito em
todos os tamanhos, pros ícones ficarem fiéis à marca. Saída em static/:
    icons/icon-192.png, icons/icon-512.png   (purpose "any")
    icons/maskable-512.png                    (logo dentro da zona segura do Android)
    icons/apple-touch-icon.png
    favicon.png                               (aba do navegador)
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow não instalado. Rode: pip install pillow")

RAIZ = Path(__file__).resolve().parent.parent
LOGO = RAIZ / "static" / "img" / "logo-esg.jpeg"
PRETO = (8, 8, 10)


def tile(base: "Image.Image", px: int, escala: float) -> "Image.Image":
    lado = int(px * escala)
    red = base.copy()
    red.thumbnail((lado, lado), Image.LANCZOS)
    cv = Image.new("RGB", (px, px), PRETO)
    cv.paste(red, ((px - red.width) // 2, (px - red.height) // 2))
    return cv


def main() -> int:
    if not LOGO.exists():
        sys.exit(f"Logo não encontrado em {LOGO}")
    logo = Image.open(LOGO).convert("RGB")
    (RAIZ / "static" / "icons").mkdir(parents=True, exist_ok=True)
    saidas = {
        "icons/icon-192.png": (192, 0.92),
        "icons/icon-512.png": (512, 0.92),
        "icons/maskable-512.png": (512, 0.74),   # zona segura (Android corta ~10% de cada lado)
        "icons/apple-touch-icon.png": (180, 0.92),
        "favicon.png": (64, 0.96),
    }
    for nome, (px, esc) in saidas.items():
        dest = RAIZ / "static" / nome
        tile(logo, px, esc).save(dest)
        print(f"{nome}: {px}x{px}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
