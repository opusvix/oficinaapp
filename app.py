"""Ponto de entrada do app OficinaApp."""
from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask, render_template, redirect, url_for
from dotenv import load_dotenv

load_dotenv()  # lê .env antes da configuração

from flask_login import LoginManager, current_user, login_required
from flask_bcrypt import Bcrypt

from core.db import get_db, init_db
from core.auth import auth_bp, login_manager, User, bootstrap_admin, aplicar_auto_liberacoes
from core.security import security_bp, init_security
from core.applog import init_applog, log_event
from core.menu import init_menu
from core.tempo import data_hora, so_data
from modules.admin import admin_bp
from modules.notificacoes import notificacoes_bp
from modules.clientes import clientes_bp
from modules.estoque import estoque_bp
from modules.os import os_bp
from modules.financeiro import financeiro_bp
from modules.agenda import agenda_bp
from modules.relatorios import relatorios_bp
from modules.leiame import leiame_bp
from modules.preferencias import pref_bp
from core.formato import documento, moeda
from core.pwa import init_pwa


def _secret_key() -> str:
    """SECRET_KEY só do ambiente. Sem padrão no código: chave conhecida assina
    sessão que qualquer um forja (Vazamento_de_Chaves)."""
    chave = os.getenv("SECRET_KEY", "")
    if len(chave) < 32:
        raise RuntimeError(
            "SECRET_KEY ausente ou curta (mínimo 32 caracteres). Gere com "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "e ponha no .env (local) ou na aba Ambiente do EasyPanel."
        )
    return chave


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    # Cookie Secure só desliga em dev local (http://127.0.0.1). Sem FLASK_ENV,
    # vale o seguro: o servidor sobe com Secure ligado.
    em_dev = os.getenv("FLASK_ENV") == "development"

    # Configuração
    app.config.from_mapping(
        SECRET_KEY=_secret_key(),
        DATABASE=os.path.join(app.instance_path, "oficina.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=not em_dev,
        SESSION_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=not em_dev,
        REMEMBER_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        # Teto do corpo do request: a foto aceita 5 MB (core/upload.py), mas sem
        # este teto o servidor recebia o arquivo INTEIRO antes de recusar (1 GB
        # enchia disco/memória). Acima disto o Flask responde 413 sem ler o resto.
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    )
    app.config.from_prefixed_env()  # lê variáveis FLASK_* e APP_*

    # Garante pasta instance
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Extensões
    bcrypt = Bcrypt(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar."

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(notificacoes_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(estoque_bp)
    app.register_blueprint(os_bp)
    app.register_blueprint(financeiro_bp)
    app.register_blueprint(agenda_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(leiame_bp)
    app.register_blueprint(pref_bp)

    # Segurança WEB (CSRF, headers, rate limit, ProxyFix)
    # Application log em JSON no stdout (Padrao_Logging_Estruturado): antes dos
    # outros init_* pra o request_id já estar setado em qualquer evento
    init_applog(app)

    init_security(app)

    # Menu da sidebar por permissão + badge de notificações (todos os templates)
    init_menu(app)

    # PWA: manifest, service worker da raiz, página offline (core/pwa.py)
    init_pwa(app)

    # Datas: o banco guarda UTC, a tela mostra hora local (core/tempo.py)
    app.add_template_filter(data_hora, "data_hora")
    app.add_template_filter(so_data, "so_data")
    # Dinheiro em real brasileiro (core/formato.py): 1234.5 -> R$ 1.234,50
    app.add_template_filter(moeda, "moeda")
    app.add_template_filter(documento, "documento")  # CPF/CNPJ com máscara
    app.add_template_filter(lambda d: (d[8:10] + "/" + d[5:7] + "/" + d[:4]) if d and len(d) >= 10 else "—",
                            "dia")   # 'AAAA-MM-DD' (dia local, sem fuso) -> 'dd/mm/aaaa'

    # Inicializa banco + admin inicial via variáveis de ambiente
    with app.app_context():
        init_db()
        bootstrap_admin()
        aplicar_auto_liberacoes()  # módulo novo já nasce liberado nos perfis configurados

    # Rota raiz
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        return redirect(url_for("auth.login"))

    # Home (pós-login)
    @app.route("/home")
    @login_required
    def home():
        from modules.inicio import painel
        return render_template("home.html", p=painel())

    # Health check
    @app.route("/health")
    def health():
        return {"status": "ok"}

    # O navegador pede /favicon.ico sozinho; manda pro SVG (o link já aponta pra lá)
    @app.route("/favicon.ico")
    def favicon_ico():
        return redirect(url_for("static", filename="favicon.svg"), code=308)

    # Páginas de erro amigáveis (nada de página cru do Werkzeug)
    paginas = {
        400: ("ph-warning-circle", "Pedido inválido",
              "A requisição não passou pela validação. Volte e tente de novo."),
        403: ("ph-lock", "Sem permissão",
              "Seu perfil não tem acesso a esta área. Fale com o administrador."),
        404: ("ph-map-pin", "Página não encontrada",
              "O endereço não existe ou foi movido."),
        413: ("ph-file-x", "Arquivo grande demais",
              "O envio passou do limite. Fotos até 5 MB: reduza a imagem e tente de novo."),
        500: ("ph-bug", "Algo quebrou",
              "O erro foi registrado. Tente de novo; se persistir, avise o suporte."),
    }

    def _erro(codigo: int):
        # ordem da tupla em `paginas`: (ícone, título, mensagem). Estava trocada:
        # a página 404 mostrava "ph-map-pin" como título.
        icone, titulo, mensagem = paginas.get(
            codigo, ("ph-warning-circle", "Erro", "Algo deu errado.")
        )
        destino = url_for("home") if current_user.is_authenticated else url_for("auth.login")
        return render_template(
            "erro.html", codigo=codigo, titulo=titulo, icone=icone,
            mensagem=mensagem, destino=destino,
        ), codigo

    @app.after_request
    def _log_403(resp):
        # 403 = autorização vertical negada (Padrao_Logging_Estruturado). O IDOR
        # (autorização horizontal) devolve 404 e já é logado em modules/os.
        if resp.status_code == 403:
            log_event("ACESSO_NEGADO_403", level="WARN")
        return resp

    for cod in paginas:
        # O Flask chama o handler COM a exceção; ignoramos e usamos o código fixo.
        app.register_error_handler(cod, lambda e, c=cod: _erro(c))

    return app


app = create_app()


if __name__ == "__main__":
    # ABRIR_NAVEGADOR=1 (usado pelo atalho do pacote Windows) abre o navegador
    # sozinho logo após o servidor subir. Fica fora de testes e do Docker, que
    # não definem essa variável. O reloader roda o main duas vezes; o guard do
    # WERKZEUG_RUN_MAIN evita abrir duas abas quando FLASK_DEBUG=1.
    if os.getenv("ABRIR_NAVEGADOR") == "1" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()

    # Roda em 127.0.0.1:5000 (uso local pelo iniciar.bat). Debug (recarrega ao salvar e
    # mostra o console do Werkzeug, que executa código) só com FLASK_DEBUG=1 de propósito.
    # No servidor quem sobe o app é o gunicorn (Dockerfile), não este bloco.
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")