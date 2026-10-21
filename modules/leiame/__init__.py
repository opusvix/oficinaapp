"""Guia rápido (Fase 9, Estrutura_de_Pastas: modules/leiame/ com item na sidebar).

Tela própria de ajuda, separada das telas de trabalho (Tela_Nao_Tem_Manual: tela
de sistema não abre com parágrafo; o passo a passo mora aqui). Cada tópico só
aparece pra quem pode VER o módulo dele, e termina com o atalho pra tela certa.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, url_for
from flask_login import current_user, login_required

leiame_bp = Blueprint("leiame", __name__, url_prefix="/leiame")

# (módulo que precisa VER, ícone, título, passos, endpoint do atalho, rótulo do atalho)
TOPICOS = [
    ("os", "ph-wrench", "Abrir uma ordem de serviço", [
        "Em Ordens de Serviço, clique em Nova OS.",
        "Escolha o cliente e o equipamento. Sem patrimônio, o sistema cria o ESG + número da OS.",
        "Tire a foto ANTES na tela da OS e descreva o defeito.",
     ], "os.listar", "Ir para Ordens de Serviço"),
    ("os", "ph-paper-plane-tilt", "Mandar o orçamento pro cliente", [
        "Na OS, lance as peças e a mão de obra: o total do orçamento é a soma dos itens.",
        "Clique em Gerar link e depois em Enviar no WhatsApp.",
        "O cliente aprova ou recusa pelo link, sem senha. Recusado cobra só o deslocamento.",
     ], "os.listar", "Ir para Ordens de Serviço"),
    ("os", "ph-check-circle", "Executar e entregar", [
        "Com a OS aprovada, faça o conserto e tire a foto DEPOIS.",
        "Descreva o que foi feito e ligue o Testei o funcionamento.",
        "Clique em Pedir validação ENTREGUE ao cliente: ele confere pelo link e assina na tela.",
        "Ao assinar, a peça sai do estoque e a conta a receber nasce sozinha.",
     ], "os.listar", "Ir para Ordens de Serviço"),
    ("agenda", "ph-calendar", "Marcar visita e montar a rota", [
        "Em Agenda e Rotas, clique no + do dia ou em Agendar na lista de OS sem visita.",
        "OS sem técnico passa a ser do técnico escolhido.",
        "Na aba Rotas do dia, as visitas aparecem agrupadas por bairro, com o link do mapa.",
     ], "agenda.semana", "Ir para a Agenda"),
    ("caixa", "ph-cash-register", "Abrir e fechar o caixa", [
        "Abra o caixa com o troco da gaveta antes de receber em dinheiro.",
        "Suprimento é dinheiro que entra sem venda; sangria é dinheiro que sai sem conta.",
        "No fim do dia, conte a gaveta e feche: a diferença fica registrada.",
     ], "financeiro.caixa", "Ir para o Caixa"),
    ("contas_receber", "ph-coins", "Receber uma conta", [
        "Em Contas a Receber, clique no ícone de baixa da linha.",
        "Escolha a forma de pagamento. Dinheiro pede o caixa aberto.",
        "Depois de recebida, o ícone de recibo gera o recibo pra imprimir ou salvar em PDF.",
     ], "financeiro.receber", "Ir para Contas a Receber"),
    ("relatorios", "ph-chart-bar", "Tirar um relatório", [
        "Em Relatórios, escolha a aba e o período.",
        "No menu da tabela, Exportar CSV ou Excel leva as linhas filtradas.",
     ], "relatorios.index", "Ir para Relatórios"),
]

TOPICOS_GERAIS = [
    ("ph-device-mobile", "Instalar no celular", [
        "Android (Chrome): menu de três pontos, Instalar app.",
        "iPhone (Safari): botão de compartilhar, Adicionar à Tela de Início.",
        "Precisa do endereço com https (o do servidor). Sem internet, o app mostra um aviso e espera o sinal voltar.",
    ]),
    ("ph-lock-key", "Senha e sessão", [
        "Sessão parada por muito tempo sai sozinha: é só entrar de novo.",
        "Errou a senha várias vezes: o acesso trava por alguns minutos.",
        "Esqueceu a senha: peça ao administrador pra redefinir.",
    ]),
]


@leiame_bp.route("/")
@login_required
def index():
    if not current_user.pode("leiame", "ver"):
        abort(403)
    topicos = [{"icone": ic, "titulo": t, "passos": ps, "link": url_for(ep), "link_rotulo": lr}
               for mod, ic, t, ps, ep, lr in TOPICOS if current_user.pode(mod, "ver")]
    gerais = [{"icone": ic, "titulo": t, "passos": ps} for ic, t, ps in TOPICOS_GERAIS]
    return render_template("leiame/index.html", topicos=topicos, gerais=gerais)
