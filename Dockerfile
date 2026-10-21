# OficinaApp - imagem de produção (EasyPanel ou qualquer host com Docker)
# Passo a passo do deploy e da migração dos dados: MIGRACAO.md
FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências antes do código: a camada só refaz quando o lockfile muda
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuário sem privilégio; instance/ (banco SQLite) e static/uploads/ (fotos) são
# os dois volumes persistentes: sem volume, cada deploy apaga os dados.
RUN useradd --create-home --uid 1000 oficina \
    && mkdir -p /app/instance /app/static/uploads \
    && chown -R oficina:oficina /app/instance /app/static/uploads
USER oficina

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# 1 worker com threads: o limite de requisições (core/security.py) mora na memória
# do processo; com vários workers cada um contaria separado e o limite valeria N vezes.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--worker-class", "gthread", "--timeout", "60", "--access-logfile", "-"]
