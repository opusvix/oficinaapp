"""PWA (Padrao_PWA_Notificacoes): manifest, service worker e página offline.

- Manifest DINÂMICO: nome vem de configuracao.empresa_nome (o mesmo do recibo),
  cache no-cache pra troca de nome aparecer na hora.
- Service worker servido da RAIZ (/service-worker.js) com Service-Worker-Allowed: /,
  senão o escopo vira /static/ e ele não controla as telas.
- O SW guarda só arquivo estático e a página /offline. Tela com dado (OS, cliente,
  caixa) NUNCA vai pro cache: o celular do técnico pode ser emprestado e o cache
  do navegador não respeita logout.
- Desvios da nota: ícone fixo gerado do favicon (scripts/gerar_icones.py), porque
  o app não tem upload de logo; push nativo fora do escopo V1 (PLANO, "Fora de escopo").
"""
from __future__ import annotations

import json

from flask import Flask, Response, render_template, send_from_directory

from core.db import query_one

COR_TEMA = "#F28333"        # laranja da marca ESG (tokens.css --accent): manifest exige cor literal
VERSAO_SW = "oficina-v2"    # troque quando mudar a lista do cache do SW


def _nome_empresa() -> str:
    try:
        row = query_one("SELECT valor FROM configuracao WHERE chave = 'empresa_nome'")
        return (row["valor"] if row and row["valor"] else "OficinaApp").strip()
    except Exception:
        return "OficinaApp"


def init_pwa(app: Flask) -> None:
    @app.context_processor
    def _cor_tema():
        return {"pwa_cor_tema": COR_TEMA}

    @app.route("/manifest.webmanifest")
    def manifest():
        nome = _nome_empresa()
        m = {
            "name": nome,
            "short_name": nome[:12],
            "description": "Ordens de serviço, agenda e financeiro da oficina",
            "lang": "pt-BR",
            "start_url": "/home",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#ffffff",
            "theme_color": COR_TEMA,
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        }
        r = Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json")
        r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return r

    @app.route("/service-worker.js")
    def service_worker():
        r = send_from_directory(app.static_folder, "service-worker.js")
        r.headers["Content-Type"] = "application/javascript; charset=utf-8"
        r.headers["Service-Worker-Allowed"] = "/"
        r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return r

    @app.route("/offline")
    def offline():
        return render_template("offline.html", empresa=_nome_empresa())
