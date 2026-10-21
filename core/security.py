"""Segurança WEB: CSRF, headers, rate limit, ProxyFix."""
from __future__ import annotations

import time
from functools import wraps
from typing import Callable

from flask import (
    Blueprint,
    Flask,
    Request,
    abort,
    current_app,
    flash,
    g,
    redirect,
    request,
    session,
    url_for,
)
from flask_login import current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

from core.auditoria import log_acesso
from core.db import query_one


# ──────────────────────────────────────────────────────────────────────────────
# CSRF
# ──────────────────────────────────────────────────────────────────────────────

_CSRF_KEY = "_csrf_token"


def gerar_csrf_token() -> str:
    """Gera token CSRF para a sessão atual."""
    if _CSRF_KEY not in session:
        import secrets
        session[_CSRF_KEY] = secrets.token_hex(32)
    return session[_CSRF_KEY]


def validar_csrf(token: str) -> bool:
    """Valida token CSRF (constant-time compare)."""
    import hmac
    esperado = session.get(_CSRF_KEY, "")
    return hmac.compare_digest(esperado, token)


def _token_recebido() -> str:
    """Token CSRF enviado pelo form ou por header.

    Aceita X-CSRF-Token (nosso) e X-CSRFToken (alias): o TabelaAvancada manda
    por `X-CSRFToken`, e nome de header é sensível à caixa no WSGI.
    """
    return (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
    )


def _csrf_negado(rota: str):
    """Resposta a token ausente/inválido: volta pra página com aviso, não 400 cru."""
    from core.applog import log_event
    log_event("CSRF_INVALIDO", level="WARN", rota=rota)
    # XHR/fetch quer status explícito; navegador leva flash e volta pro form.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        abort(400, "CSRF token inválido ou ausente.")
    flash("Sessão expirada. Recarregue a página e tente de novo.", "erro")
    # Sem referrer (navegador com privacidade, curl), cai na home e não num 400 cru.
    return redirect(request.referrer or url_for("home"))


def csrf_protect(f: Callable) -> Callable:
    """Decorator para proteger rotas POST com CSRF."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "POST":
            token = _token_recebido()
            if not token or not validar_csrf(token):
                return _csrf_negado(request.path)
        return f(*args, **kwargs)

    return wrapper


def init_csrf(app: Flask) -> None:
    """Registra token CSRF disponível em templates como função ({{ csrf_token() }})."""

    @app.context_processor
    def inject_csrf():
        return {"csrf_token": gerar_csrf_token}

    app.before_request(_csrf_before_request)


def _csrf_before_request():
    """Auto-protege POSTs que não são de login/upload (que têm validação própria)."""
    if request.method != "POST":
        return
    # Rotas que dispensam CSRF (login, logout, upload com token próprio)
    if request.path.startswith(("/auth/login", "/auth/logout", "/upload")):
        return
    # Verifica se já tem decorator csrf_protect (pula se já validou)
    if getattr(request, "_csrf_validated", False):
        return
    token = _token_recebido()
    if token and validar_csrf(token):
        return
    return _csrf_negado(request.path)


# ──────────────────────────────────────────────────────────────────────────────
# Headers de segurança
# ──────────────────────────────────────────────────────────────────────────────

def csp_nonce() -> str:
    """Nonce do request: só <script> com nonce="{{ csp_nonce() }}" roda inline."""
    if "csp_nonce" not in g:
        import secrets
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def init_security_headers(app: Flask) -> None:
    """Adiciona headers de segurança em todas as respostas."""

    @app.context_processor
    def inject_nonce():
        return {"csp_nonce": csp_nonce}

    @app.after_request
    def add_security_headers(response):
        # Previne clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Previne MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # O app não usa câmera, microfone nem localização pelo navegador
        # (foto vem por upload de arquivo, que não depende de permissão)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # CSP (CSRF_Cookies_Headers): script só do próprio site ou com o nonce do
        # request. Sem 'unsafe-inline' em script: XSS injetado não executa.
        # Handler inline (onclick=) também não roda: o HTML usa data-clique e o
        # delegador do main.js. style-src segue com 'unsafe-inline' (style= no HTML).
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{csp_nonce()}'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Content-Security-Policy"] = csp
        # HSTS (apenas em produção com HTTPS)
        if not app.debug and request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ──────────────────────────────────────────────────────────────────────────────
# Rate limit (simples, em memória por IP)
# ──────────────────────────────────────────────────────────────────────────────

_RATE_LIMITS = {}  # {ip: [(timestamp, endpoint), ...]}
_DEFAULT_LIMIT = 100  # req/min
_LOGIN_LIMIT = 10     # req/min em /auth/login


def get_client_ip() -> str:
    """IP do cliente. O ProxyFix (x_for=1) já corrigiu o remote_addr contando do
    fim do X-Forwarded-For. NÃO reler o header: o primeiro item é escrito pelo
    cliente e é forjável (burla o rate limit e envenena bloqueio por IP)."""
    return request.remote_addr or "0.0.0.0"


def _limpar_antigos(limite_segundos: int = 60) -> None:
    agora = time.time()
    for ip in list(_RATE_LIMITS.keys()):
        _RATE_LIMITS[ip] = [t for t in _RATE_LIMITS[ip] if agora - t[0] < limite_segundos]
        if not _RATE_LIMITS[ip]:
            del _RATE_LIMITS[ip]


def rate_limit(limite: int = _DEFAULT_LIMIT, janela: int = 60) -> Callable:
    """Decorator para limitar requisições por IP."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = get_client_ip()
            _limpar_antigos(janela)
            agora = time.time()
            requisicoes = _RATE_LIMITS.get(ip, [])
            # Conta só para este endpoint
            count = sum(1 for t, ep in requisicoes if ep == request.endpoint)
            if count >= limite:
                from flask import abort
                from core.applog import log_event
                log_event("RATE_LIMIT_HIT", level="WARN", endpoint=request.endpoint, limite=limite)
                abort(429, "Muitas requisições. Tente novamente em instantes.")
            _RATE_LIMITS.setdefault(ip, []).append((agora, request.endpoint))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def init_rate_limit(app: Flask) -> None:
    """Aplica rate limit global (exceto rotas de health/static).

    Login: só o POST conta pra trava de força bruta por IP. Antes o GET da
    tela também era contado, e 10 recargas de /auth/login já davam 429 —
    achado pela fumaca_fase1 (429 no teste de notificação).
    """
    @app.before_request
    def _global_rate_limit():
        # Controle_de_IP: o limite é de POST por IP por minuto. Leitura (GET/HEAD)
        # não conta: contar GET travava navegação normal e sonda de saúde
        # (o HEAD / do monitor batia 100/min e derrubava a home com 429).
        if request.method != "POST" or request.path.startswith(("/static", "/health")):
            return
        if request.endpoint == "auth.login":
            rate_limit(_LOGIN_LIMIT, 60)(lambda: None)()
        else:
            rate_limit(_DEFAULT_LIMIT, 60)(lambda: None)()


# ──────────────────────────────────────────────────────────────────────────────
# ProxyFix (para rodar atrás de Traefik/Nginx no EasyPanel)
# ──────────────────────────────────────────────────────────────────────────────

def init_proxy_fix(app: Flask) -> None:
    """Configura ProxyFix para ler headers do proxy reverso."""
    # x_for=1, x_proto=1, x_host=1, x_prefix=1
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


# ──────────────────────────────────────────────────────────────────────────────
# Timeout de sessão por inatividade (Timeout_de_Sessao)
# ──────────────────────────────────────────────────────────────────────────────

TIMEOUT_PADRAO_MIN = 60


def timeout_sessao_min() -> int:
    """Minutos de inatividade até exigir login de novo (0 desliga).

    Vem da tabela configuracao: muda no banco e vale no próximo request.
    """
    row = query_one(
        "SELECT valor FROM configuracao WHERE chave = 'session_timeout_min' AND D_E_L_E_T = 0"
    )
    try:
        return int(row["valor"]) if row else TIMEOUT_PADRAO_MIN
    except (TypeError, ValueError):
        return TIMEOUT_PADRAO_MIN


def init_timeout_sessao(app: Flask) -> None:
    @app.before_request
    def _timeout_inatividade():
        if request.path.startswith(("/static", "/health")):
            return
        if not current_user.is_authenticated:
            return
        agora = int(time.time())
        ultima = session.get("ultima_atividade", agora)
        limite = timeout_sessao_min()
        if limite > 0 and agora - ultima > limite * 60:
            log_acesso("SESSAO_EXPIRADA", current_user.id, f"parado {(agora - ultima) // 60} min")
            logout_user()
            session.clear()
            return redirect(url_for("auth.login", expirado=1))
        session["ultima_atividade"] = agora


# ──────────────────────────────────────────────────────────────────────────────
# Controle de IP (Controle_de_IP): off | monitor | block, padrão off
# ──────────────────────────────────────────────────────────────────────────────

# Regra de ouro do tráfego: rota pública NUNCA é filtrada por IP. O link do
# cliente (aprovar, assinar a entrega, comprovante) fica fora da trava.
ROTAS_PUBLICAS_IP = ("/static", "/health", "/favicon.ico", "/os/public/")


def ip_bloqueado(ip: str) -> bool:
    agora = int(time.time())
    row = query_one(
        """SELECT 1 FROM ip_regras
            WHERE ip = ? AND tipo = 'block' AND D_E_L_E_T = 0
              AND (expira_em IS NULL OR expira_em > ?)
              AND NOT EXISTS (SELECT 1 FROM ip_regras a
                               WHERE a.ip = ? AND a.tipo = 'allow' AND a.D_E_L_E_T = 0)""",
        (ip, agora, ip),
    )
    return row is not None


def init_controle_ip(app: Flask) -> None:
    @app.before_request
    def _controle_ip():
        if request.path.startswith(ROTAS_PUBLICAS_IP):
            return
        row = query_one(
            "SELECT valor FROM configuracao WHERE chave = 'ip_protecao_modo' AND D_E_L_E_T = 0"
        )
        modo = (row["valor"] if row else "off") or "off"
        if modo not in ("monitor", "block"):
            return
        ip = get_client_ip()
        if not ip_bloqueado(ip):
            return
        if modo == "monitor":
            log_acesso("IP_BLOQUEIO_MONITOR", None, f"path={request.path}")
            return
        log_acesso("IP_BLOQUEADO", None, f"path={request.path}")
        abort(403)


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização única
# ──────────────────────────────────────────────────────────────────────────────

security_bp = Blueprint("security", __name__)


# Rotas liberadas pra quem ainda precisa trocar a senha: a própria troca, sair e o
# que a tela de troca carrega (estático, PWA)
LIBERADAS_TROCA_SENHA = {"auth.trocar_senha", "auth.logout", "static", "health",
                         "manifest", "service_worker", "offline", "favicon_ico"}


def init_troca_obrigatoria(app: Flask) -> None:
    """Senha sorteada (admin inicial, usuário novo, redefinição) tem que ser trocada.

    Antes só o login redirecionava: digitando outro endereço, a pessoa seguia com a
    senha que o administrador conhece. Agora toda rota (menos as liberadas) manda
    pra troca enquanto precisa_trocar_senha = 1.
    """
    @app.before_request
    def _exige_troca():
        if not current_user.is_authenticated or not getattr(current_user, "precisa_trocar_senha", False):
            return
        if request.endpoint in LIBERADAS_TROCA_SENHA:
            return
        return redirect(url_for("auth.trocar_senha"))


def init_security(app: Flask) -> None:
    """Inicializa todos os módulos de segurança."""
    # Timeout primeiro: sessão vencida sai antes de qualquer outra checagem
    init_timeout_sessao(app)
    init_troca_obrigatoria(app)
    init_controle_ip(app)
    init_csrf(app)
    init_security_headers(app)
    init_proxy_fix(app)
    init_rate_limit(app)