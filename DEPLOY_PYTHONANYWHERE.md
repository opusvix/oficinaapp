# Publicar a DEMONSTRAÇÃO online (PythonAnywhere, grátis)

Guia passo a passo pra deixar a demo do OficinaApp no ar num endereço tipo
`https://SEUUSUARIO.pythonanywhere.com`. Não precisa cartão. Leva ~20 minutos.

> A **página de divulgação** fica no Netlify (já no ar). Aqui é a **demo do sistema**
> em si — um servidor Python, que o Netlify não hospeda. São dois lugares, ligados
> pelo botão "Testar online" da página.

---

## Antes de começar
Gere o pacote do código (uma vez, no seu computador):

```bash
.venv/Scripts/python.exe scripts/empacotar_fonte.py
```

Isso cria **`dist/OficinaApp-fonte.zip`** (uns 300 KB). É esse arquivo que você sobe.

---

## 1. Criar a conta
1. Entre em **https://www.pythonanywhere.com** → **Pricing & signup** → **Create a Beginner account** (o grátis).
2. Confirme o e-mail e faça login. Você cai no **Dashboard**.

## 2. Subir o código
1. No menu de cima, abra a aba **Files**.
2. Em **"Upload a file"**, envie o **`OficinaApp-fonte.zip`**.
3. Abra a aba **Consoles** → **Bash** (abre um terminal no navegador) e rode:
   ```bash
   unzip OficinaApp-fonte.zip
   ```
   Isso cria a pasta **`oficinaapp`** com o código.

## 3. Instalar as dependências (ambiente virtual)
Ainda no console **Bash**, rode uma linha por vez:
```bash
mkvirtualenv --python=python3.12 oficina
pip install -r oficinaapp/requirements.txt
```
A primeira cria o ambiente `oficina`; a segunda instala Flask e o resto (demora ~2 min).

> Guarde o caminho do ambiente: **`/home/SEUUSUARIO/.virtualenvs/oficina`**
> (troque `SEUUSUARIO` pelo seu nome de usuário do PythonAnywhere).

## 4. Criar o site (Web app)
1. Abra a aba **Web** → **Add a new web app** → **Next**.
2. Escolha **Manual configuration** (NÃO escolha "Flask") → **Python 3.12** → **Next**.
3. O site é criado "vazio". Agora ajuste 3 campos nessa página **Web**:
   - **Source code:** `/home/SEUUSUARIO/oficinaapp`
   - **Working directory:** `/home/SEUUSUARIO/oficinaapp`
   - **Virtualenv:** `/home/SEUUSUARIO/.virtualenvs/oficina`

## 5. Apontar o WSGI (o "ligador" do app)
1. Ainda na aba **Web**, clique no link do **WSGI configuration file**
   (algo como `/var/www/SEUUSUARIO_pythonanywhere_com_wsgi.py`).
2. **Apague tudo** o que estiver no arquivo e **cole o conteúdo** de
   `oficinaapp/scripts/wsgi_pythonanywhere.py`.
3. Troque o que está marcado:
   - `SEUUSUARIO` (nas duas aparições do caminho) pelo seu usuário.
   - `SECRET_KEY`: gere 64 caracteres no console Bash e cole:
     ```bash
     python3 -c "import secrets;print(secrets.token_hex(32))"
     ```
   - (Opcional) troque a senha pública da demo em `ADMIN_SENHA_INICIAL`.
4. **Save** (botão no topo do editor).

## 6. Ligar
1. Volte à aba **Web** e clique no botão verde **Reload**.
2. Abra **`https://SEUUSUARIO.pythonanywhere.com`**.
3. Na tela de login aparece a **caixa de demonstração** com e-mail e senha —
   clique em "Preencher automaticamente" e entre. Pronto, a demo está no ar! 🎉

---

## Depois de publicar
- **Cole o endereço na página de divulgação:** no `site/index.html`, troque a linha
  `var URL_DEMO = "#";` por `var URL_DEMO = "https://SEUUSUARIO.pythonanywhere.com";`
  e republique no Netlify (arrastar a pasta `site/` de novo).
- **Manter limpo:** logado como admin, há o botão **"Reiniciar demonstração"** no
  topo — zera o que os visitantes mexeram e devolve os dados de exemplo.
- **Atenção do plano grátis:** o site é pausado após ~1 mês sem acesso; o
  PythonAnywhere manda um e-mail com um botão pra reativar num clique. Pra tirar essa
  limitação, o plano pago mais barato (~US$5/mês) deixa sempre no ar.
- **Atualizar o código depois:** gere o zip de novo, suba, no Bash
  `rm -rf oficinaapp && unzip -o OficinaApp-fonte.zip`, e **Reload** na aba Web.
