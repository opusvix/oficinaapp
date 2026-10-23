# MODELO do arquivo WSGI do PythonAnywhere (demonstração do OficinaApp).
#
# No PythonAnywhere, aba "Web" -> link do "WSGI configuration file"
# (algo como /var/www/SEUUSUARIO_pythonanywhere_com_wsgi.py). APAGUE tudo o
# que estiver lá e cole ESTE conteúdo, trocando as 4 coisas marcadas com <...>.
# Depois clique em "Reload" na aba Web. Passo a passo completo: DEPLOY_PYTHONANYWHERE.md
#
# Por que definir as variáveis aqui: o PythonAnywhere não lê o .env; então o
# acesso de demo, o segredo e o modo demonstração entram por estas linhas.

import os
import sys

# 1) Caminho da pasta do projeto no PythonAnywhere (troque SEUUSUARIO).
CAMINHO = "/home/SEUUSUARIO/oficinaapp"            # <-- troque SEUUSUARIO
if CAMINHO not in sys.path:
    sys.path.insert(0, CAMINHO)

# 2) Segredo das sessões: gere 64 caracteres aleatórios e cole aqui.
#    No console Bash do PythonAnywhere: python3 -c "import secrets;print(secrets.token_hex(32))"
os.environ["SECRET_KEY"] = "<COLE_AQUI_64_CARACTERES_ALEATORIOS>"   # <-- troque

# 3) Acesso de demonstração que aparece na tela de login (pode deixar assim).
os.environ["ADMIN_EMAIL"] = "demo@oficinaapp.com.br"
os.environ["ADMIN_SENHA_INICIAL"] = "demo1234"     # <-- senha pública da demo (troque se quiser)

# 4) Liga o modo demonstração (caixa de acesso no login + botão "Reiniciar demo").
os.environ["MODO_DEMO"] = "1"

# Sobe o app. O banco de exemplo é criado e semeado sozinho na primeira carga.
from app import app as application   # noqa: E402
