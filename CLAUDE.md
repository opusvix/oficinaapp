# OficinaApp

> Projeto do Joviano. Os padrões técnicos, visuais, de segurança e de copy
> vivem na base de conhecimento, e quem os carrega é o GENESIS, sob demanda:
> /genesis-iniciar para trabalho novo, /genesis-continuar para retomar.
> Este arquivo descreve só o que é específico DESTE projeto.

## Como rodar

```bash
# Windows
iniciar.bat

# Ou manual
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Roda em http://127.0.0.1:5000 (Flask dev server). SQLite em instance/oficina.db.

## Como publicar

Deploy em servidor próprio (VPS/Hostinger) com Gunicorn + Nginx + systemd.
Variáveis em .env de produção: SECRET_KEY, DATABASE_URL (pode trocar para Postgres), FLASK_ENV=production.
HTTPS via Let's Encrypt. Backups automáticos do SQLite.

## STACK TRAVADA

```yaml
Framework: Flask        # único framework permitido no back-end
Tipo: Pagina_WEB_SQLite # nota de tipo escolhida no DIA 2
Regime: WEB             # segurança obrigatória, fase própria, nunca última
Entrega: iniciar.bat    # lançador de duplo clique Windows (na raiz)
PROIBIDO: Streamlit, Gradio, FastAPI, Django, Dash, NiceGUI, Flet
```

## Stack

- Python 3.12+
- Flask 3.x + Jinja2
- SQLite (desenvolvimento) / Postgres (produção opcional)
- HTML/CSS/JS vanilla (sem build step), PWA-ready
- Phosphor Icons **self-hosted** em `static/fonts/phosphor/` (sem CDN)
- Chart.js (CDN) para dashboards

## Módulos

- **auth** — login, perfis (Admin/Técnico/Cliente), permissões, admin inicial
- **clientes** — CRM: cadastro, histórico equipamentos, endereços, contatos
- **estoque** — peças/itens: código, custo, venda, alerta mínimo, entrada/saída
- **os** — Ordens de Serviço: abertura, peças usadas, descrição, assinatura digital, fluxo técnico (fotos antes/depois), aprovação/rejeição via link, PDF
- **financeiro** — PDV, caixa, recibos/notas, formas pagamento, contas a pagar/receber
- **agenda** — rotas técnicos, horários, otimização deslocamento
- **relatorios** — KPIs, dashboards, exportação

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| SECRET_KEY | Sim | Chave Flask (sessão, CSRF). Gerar: python -c "import secrets; print(secrets.token_hex(32))" |
| DATABASE_URL | Não | sqlite:///instance/oficina.db (dev) ou postgresql://user:pass@host/db (prod) |
| FLASK_ENV | Não | development ou production |
| APP_MODE | Sim | auth (login por perfil) — define regime de segurança WEB |

## Convenções deste projeto

- **Soft delete** em todas as tabelas principais: coluna deleted_at (nullable), filtro padrão WHERE deleted_at IS NULL
- **Nomes de tabela**: singular, snake_case (cliente, ordem_servico, peca)
- **Chaves primárias**: id integer autoincrement
- **FK**: tabela_id (ex: cliente_id em ordem_servico)
- **Tag/Patrimônio equipamento**: campo obrigatório patrimonio na OS; se vazio, gera ESG{idOS} no backend
- **Perfis**: admin, tecnico, cliente — guardados em usuario.perfil
- **Aprovação OS**: token público de uso único (os_token), expira em 7 dias, valida sem login
- **Uploads**: fotos em static/uploads/os/{idOS}/ (antes/depois), limite 5MB, tipos image/*
- **PDF**: gerado via WeasyPrint (HTML → PDF), template Jinja dedicado

## Identidade visual deste projeto

Token: --accent (e --accent-suave, --accent-escura, --accent-hover, --accent-soft, --accent-sombra, --accent-texto, --accent-texto-escuro), em static/css/tokens.css
Cor da marca: #3387E9
Tema: ambos com alternador (light/dark, salva preferência em localStorage)
PROIBIDO: o hex #3387E9 aparecer em qualquer template
PROVA: grep -rn "#3387E9" templates/ volta vazio

## Ritmo dos ajudantes

Paralelismo: auto

## Armadilhas

- **Segurança WEB obrigatória**: CSRF em todo POST, headers seguros, rate limit em login, validação server-side. Não pular fase de segurança.
- **Auth por perfil**: nasce com tela de login + tela de perfis/permissões + admin inicial padrão. Não diluir.
- **Toggle On/Off**: usa span.cv-sw + input + label, tamanho 42x24, ligado em verde #16a34a. PROIBIDO: checkbox nativo visível, <select>, setinha.
- **Select nativo proibido**: sempre Componente_SelectBusca (com busca).
- **Menu lateral + ícones**: obrigatórios (todo projeto com tela tem).
- **Alternador de tema**: exige par de tokens para cada cor de superfície/texto. Se quebrado, metade das telas falha.
- **PDF WeasyPrint**: precisa dependências de sistema (libpango, libcairo). No Windows, instalar GTK Runtime.
