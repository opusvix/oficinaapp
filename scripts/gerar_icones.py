"""Gera os ícones PNG do PWA a partir do desenho do static/favicon.svg.

Roda uma vez (ou quando a marca mudar), fora do app:
    python scripts/gerar_icones.py

Sem Pillow nem cairo: o desenho do favicon é geometria simples (quadrado de
canto arredondado, anel e uma haste), então cada pixel é calculado direto, com
4x4 amostras por pixel pra borda sair suave, e o PNG é montado com zlib.

Saída em static/icons/:
    icon-192.png, icon-512.png   quadrado arredondado (purpose "any")
    maskable-512.png             fundo cheio até a borda, desenho dentro dos 80%
                                 centrais (zona segura do Android, purpose "maskable")
    apple-touch-icon.png         180x180, fundo cheio (o iOS arredonda sozinho)
"""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "static" / "icons"

AZUL = (0x33, 0x87, 0xE9)      # --accent (tokens.css); PNG não lê variável CSS
BRANCO = (255, 255, 255)


def _dist_segmento(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dentro_arredondado(x, y, lado, raio):
    """Ponto (coordenadas 0..lado) dentro do quadrado de canto arredondado."""
    cx = min(max(x, raio), lado - raio)
    cy = min(max(y, raio), lado - raio)
    return math.hypot(x - cx, y - cy) <= raio


def _cor(u, v, cheio: bool):
    """Cor no ponto (u, v) do desenho de 64x64 do favicon, ou None se transparente."""
    if not cheio and not (0 <= u <= 64 and 0 <= v <= 64 and _dentro_arredondado(u, v, 64, 14)):
        return None
    d_anel = abs(math.hypot(u - 26, v - 26) - 12)
    d_haste = _dist_segmento(u, v, 34.5, 34.5, 50, 50)
    if math.hypot(u - 26, v - 26) <= 4.5:
        return AZUL
    if d_anel <= 3.5 or d_haste <= 3.5:
        return BRANCO
    return AZUL


def desenhar(tamanho: int, cheio: bool = False, escala: float = 1.0) -> bytes:
    """RGBA do ícone. `escala` < 1 encolhe o desenho pro centro (zona segura)."""
    amostras = 4
    linhas = bytearray()
    for py in range(tamanho):
        linhas.append(0)                     # filtro PNG "None" por linha
        for px in range(tamanho):
            r = g = b = a = 0.0
            for sy in range(amostras):
                for sx in range(amostras):
                    x = (px + (sx + 0.5) / amostras) / tamanho * 64
                    y = (py + (sy + 0.5) / amostras) / tamanho * 64
                    u = 32 + (x - 32) / escala
                    v = 32 + (y - 32) / escala
                    c = _cor(u, v, cheio)
                    if c is None and cheio:
                        c = AZUL
                    if c is not None:
                        r += c[0]; g += c[1]; b += c[2]; a += 255
            n = amostras * amostras
            alfa = a / n
            if alfa:
                linhas += bytes((round(r / (a / 255)), round(g / (a / 255)), round(b / (a / 255)), round(alfa)))
            else:
                linhas += b"\x00\x00\x00\x00"
    return bytes(linhas)


def png(tamanho: int, rgba: bytes) -> bytes:
    def bloco(tipo, dados):
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
    cab = struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0)   # 8 bits, RGBA
    return b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", cab) + bloco(b"IDAT", zlib.compress(rgba, 9)) + bloco(b"IEND", b"")


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    saidas = {
        "icon-192.png": (192, False, 1.0),
        "icon-512.png": (512, False, 1.0),
        "maskable-512.png": (512, True, 0.8),
        "apple-touch-icon.png": (180, True, 0.86),
    }
    for nome, (t, cheio, esc) in saidas.items():
        dados = png(t, desenhar(t, cheio, esc))
        (DESTINO / nome).write_bytes(dados)
        print(f"{nome}: {t}x{t}, {len(dados) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
