# Migração: do computador da oficina para o servidor

No computador (`iniciar.bat`) o sistema só abre ali mesmo, em `http://127.0.0.1:5000`.
Pra usar no **celular do técnico**, mandar o **link de aprovação pro cliente** e
**instalar como app** (PWA), ele precisa estar num servidor com endereço `https://`.

Este guia leva o sistema pro servidor (EasyPanel ou qualquer host com Docker) e,
se você já usava no computador, leva os dados junto.

---

## 1. O que vai pro servidor

| Item | Onde fica | Observação |
|---|---|---|
| Código | a pasta do projeto | o `Dockerfile` da raiz monta a imagem |
| Banco | `instance/oficina.db` | volume persistente (sem volume, cada deploy apaga tudo) |
| Fotos | `static/uploads/` | volume persistente |
| Segredos | variáveis de ambiente | **nunca** suba o `.env` (o `.dockerignore` já tira) |

A imagem roda com **gunicorn** na porta **8000**, 1 processo com 8 threads
(o limite de requisições fica na memória do processo; com vários processos ele
valeria em dobro). Uma oficina cabe com folga nisso.

## 2. Criar o app no EasyPanel

1. **Novo serviço > App**, origem: o repositório Git ou o upload da pasta.
2. **Build:** Dockerfile (o da raiz). Porta do container: `8000`.
3. **Ambiente** (aba Ambiente):

   ```
   SECRET_KEY=<64 caracteres: python -c "import secrets; print(secrets.token_hex(32))">
   ADMIN_EMAIL=<e-mail do administrador>
   ```

   - **Não** defina `FLASK_ENV` nem `FLASK_DEBUG` no servidor. Sem `FLASK_ENV`,
     o cookie de sessão sai `Secure` (só trafega em https), que é o certo.
   - `ADMIN_SENHA_INICIAL` vazio: a senha sai sorteada **uma vez** no log da
     primeira subida (linha `SENHA INICIAL SORTEADA`). Se você vai trazer o
     banco do computador (passo 5), o administrador já existe e nada é sorteado.
   - Opcional: `EMAIL_IGNORAR_BLOQUEIOS=<seu e-mail>` pra você nunca ficar
     travado pelo bloqueio de força bruta.

4. **Volumes** (aba Montagens), os dois do tipo volume:

   | Caminho no container | Pra quê |
   |---|---|
   | `/app/instance` | banco `oficina.db` |
   | `/app/static/uploads` | fotos |

   O container roda como usuário `oficina` (uid 1000): o volume precisa
   permitir escrita pra ele (no EasyPanel, volume novo já vem assim).

5. **Domínio:** aponte o domínio (ex.: `oficina.suaempresa.com.br`) e ligue o
   HTTPS (Let's Encrypt). O app confia em **um** proxy na frente (`ProxyFix`
   com `x_for=1`), que é o do EasyPanel: não coloque outro proxy no meio sem
   ajustar isso em `core/security.py`, senão o IP do usuário sai errado no
   bloqueio de força bruta e nos logs.

6. **Deploy.** Confira `https://<seu-domínio>/health`: tem que responder `{"status": "ok"}`.

## 3. Levar os dados do computador (se já usava)

Com o `iniciar.bat` **fechado** (banco aberto pode copiar pela metade):

1. Copie `instance\oficina.db` do computador pro volume `/app/instance`
   (pelo gerenciador de arquivos do EasyPanel ou `docker cp`).
2. Copie o conteúdo de `static\uploads\` pro volume `/app/static/uploads`.
3. Reinicie o serviço.

Usuários e senhas vêm junto: cada um entra no servidor com a mesma senha que
usava no computador. O `SECRET_KEY` do servidor pode (e deve) ser outro: ele só
assina a sessão, então a troca apenas pede login de novo.

Depois de conferir que está tudo no servidor, **pare de usar o computador**:
dois lugares recebendo OS ao mesmo tempo viram dois bancos diferentes, e não
existe junção automática.

## 4. Conferência depois do deploy

- [ ] `/health` responde ok
- [ ] Login do administrador funciona (e pede pra trocar a senha, se sorteada)
- [ ] Em **Usuários e Permissões**, crie os técnicos: cada um recebe uma senha
      provisória que aparece uma vez e troca no primeiro acesso
- [ ] Abra uma OS de teste, gere o link e abra no celular **fora do Wi-Fi da oficina**
- [ ] No celular do técnico: Chrome > Instalar app (iPhone: Safari > Compartilhar >
      Adicionar à Tela de Início)
- [ ] Apague a OS de teste (cancelar)

## 5. Cópia de segurança no servidor

O banco é um arquivo só. Pra copiar sem parar o sistema, use a cópia online do
próprio SQLite pelo console do container:

```
python -c "import sqlite3; o=sqlite3.connect('instance/oficina.db'); d=sqlite3.connect('instance/copia.db'); o.backup(d); d.close()"
```

e baixe `instance/copia.db` junto com a pasta `static/uploads`. Faça no mínimo
uma vez por semana e guarde fora do servidor.

## 6. Voltar uma versão do código

Cada fase fechada gerou um ZIP em `z_Versoes/` (nome com data e hora). Pra voltar,
publique o código desse ZIP no lugar do atual. Os volumes (banco e fotos) não
mudam com o código; só não volte pra uma versão **anterior** a uma mudança de
banco sem conferir o `00_GENESIS/LOG.md`, porque a versão antiga pode não
conhecer as colunas novas.

## Limites desta versão

- Banco SQLite: bom pra uma oficina (poucos usuários ao mesmo tempo). Não há
  suporte a Postgres nesta versão.
- Sem notificação push no celular (fora do escopo V1): o técnico vê as visitas
  no Início e na Agenda.
- Sem envio de e-mail (o projeto não tem SMTP): link do cliente vai pelo WhatsApp.
