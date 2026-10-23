"""Modo demonstração (MODO_DEMO=1).

Liga uma demo PÚBLICA e COMPARTILHADA do sistema: todo mundo entra com o mesmo
acesso de demonstração (ADMIN_EMAIL / ADMIN_SENHA_INICIAL, mostrados na tela de
login) e mexe no mesmo banco de exemplo. Pra manter limpo, o admin tem um botão
"Reiniciar demonstração" que zera tudo e devolve os dados de exemplo.

Fora da demo (MODO_DEMO != "1") nada aqui tem efeito: as funções caem fora logo
no começo, então o app normal do cliente não é tocado.

O reinício é um apagar de verdade das tabelas de dados — EXCLUSIVO da demo e à
parte da regra de negócio Nunca_DELETE_Fisico (que vale pros dados reais, onde a
exclusão é lógica por D_E_L_E_T).
"""
from __future__ import annotations

import os

from core.db import get_db

# Tabelas que o reinício PRESERVA (estrutura/segurança + o próprio admin de demo).
# Todo o resto (dados de negócio, logs, tentativas, notificações) é zerado.
_PRESERVAR = {
    "perfil", "modulo", "permissoes", "perfis_grupos_auto",
    "configuracao", "usuario", "sqlite_sequence",
}


def modo_demo() -> bool:
    return os.getenv("MODO_DEMO", "").strip() == "1"


def credenciais_demo() -> dict | None:
    """E-mail e senha mostrados na tela de login da demo (None fora da demo)."""
    if not modo_demo():
        return None
    return {
        "email": (os.getenv("ADMIN_EMAIL") or "").strip(),
        "senha": (os.getenv("ADMIN_SENHA_INICIAL") or "").strip(),
    }


# ── Dados de exemplo ──────────────────────────────────────────────────────────
def _verificador(base: str, pesos: list[int]) -> str:
    soma = sum(int(base[i]) * pesos[i] for i in range(len(pesos)))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def _cpf(base9: str) -> str:
    d1 = _verificador(base9, [10, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _verificador(base9 + d1, [11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
    return base9 + d1 + d2


def _cnpj(base12: str) -> str:
    d1 = _verificador(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _verificador(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base12 + d1 + d2


# codigo, descricao, unidade, custo, venda, estoque_atual, estoque_minimo, local
# (2 abaixo do mínimo de propósito, pra acender o alerta no painel inicial)
PECAS = [
    ("CAP-45", "Capacitor 45uF", "UN", "12.00", "38.00", "25", "8", "Gaveta 5"),
    ("CORR-10", "Correia dentada 10mm", "PC", "15.00", "42.00", "2", "6", "Prateleira C2"),
    ("FIL-AR", "Filtro de ar universal", "UN", "8.00", "19.00", "40", "10", "Gaveta 2"),
    ("MANG-12", "Mangueira silicone 12mm", "M", "6.00", "18.00", "18", "5", "Rolo 1"),
    ("RES-220", "Resistência 220V 3000W", "UN", "35.00", "85.00", "12", "4", "Prateleira A3"),
    ("TER-01", "Termostato bulbo 30-110°C", "UN", "22.00", "60.00", "3", "5", "Prateleira B1"),
]

# razao, fantasia, doc, email, tel, cep, logradouro, numero, bairro, cidade, uf
CLIENTES = [
    ("Padaria São Jorge Ltda", "Padaria São Jorge", _cnpj("112223330001"),
     "contato@padariasaojorge.com.br", "1133334444", "01310100",
     "Av. Paulista", "1500", "Bela Vista", "São Paulo", "SP"),
    ("Mercado Bom Preço Eireli", "Bom Preço", _cnpj("223334440001"),
     "fiscal@mercadobompreco.com.br", "1134445555", "03015000",
     "Rua do Oratório", "210", "Mooca", "São Paulo", "SP"),
    ("Restaurante Sabor da Terra", None, _cpf("123456789"),
     "sabordaterra@gmail.com", "11988887777", "04038000",
     "Rua Gaivota", "88", "Saúde", "São Paulo", "SP"),
    ("Clínica Odonto Bem Sorriso", "Bem Sorriso", _cnpj("334445550001"),
     "recepcao@bemsorriso.com.br", "1135556666", "04571010",
     "Av. Brigadeiro Luís Antônio", "2000", "Jardim América", "São Paulo", "SP"),
    ("Lanchonete do Zé", None, _cpf("987654321"),
     None, "11977776666", "02011000",
     "Rua Voluntários da Pátria", "305", "Santana", "São Paulo", "SP"),
    ("Supermercado Estrela do Norte Ltda", "Estrela do Norte", _cnpj("445556660001"),
     "compras@estreladonorte.com.br", "1136667777", "07034000",
     "Av. Marechal Tito", "900", "Vila Gomes Cardim", "Guarulhos", "SP"),
    ("Hamburgueria Fogo Alto", "Fogo Alto", _cnpj("556667770001"),
     "oi@fogoalto.com.br", "11966665555", "04094000",
     "Rua Borges de Medeiros", "45", "Moema", "São Paulo", "SP"),
    ("Escola Aprender e Crescer", None, _cnpj("667778880001"),
     "direcao@aprenderecrescer.edu.br", "1137778888", "05508000",
     "Rua Giovani Gronchi", "1200", "Campo Limpo", "São Paulo", "SP"),
]

# indice do cliente, patrimonio ("" = gera ESG{id}), modelo, marca, serie
EQUIPAMENTOS = [
    (0, "ESG101", "Freezer horizontal 300L", "Electrolux", "FX30A91"),
    (0, "ESG102", "Batedeira planetária 10L", "KitchenAid", "KP10WH"),
    (1, "ESG103", "Câmara fria 1 porta", "Metral", "CF1P22"),
    (1, "ESG104", "Expositor de doces 90cm", "Inbrás", "EXD90"),
    (2, "ESG105", "Fogão 6 bocas industrial", "Séries", "F6BIND"),
    (2, "", "Liquidificador 2L", "Mondial", "ML2FE"),
    (3, "ESG107", "Esterilizador autoclave", "Cristófoli", "AC12B"),
    (4, "ESG108", "Chapa elétrica 80cm", "Lion", "CH80EL"),
    (5, "ESG109", "Serra fria automática", "Bosch", "GKS190"),
    (5, "ESG110", "Compressor de ar 50L", "Schulz", "CFA50"),
    (6, "", "Fritadeira industrial 25L", "Lion", "FR25IN"),
    (7, "ESG112", "Bebedouro de bancada", "Crystal", "BBDB10"),
]


def _base_vazia(db) -> bool:
    return db.execute("SELECT COUNT(*) FROM cliente WHERE D_E_L_E_T = 0").fetchone()[0] == 0


def semear_demo(db) -> None:
    """Popula peças + clientes + equipamentos de exemplo (só se a base estiver vazia).

    As ordens de serviço ficam de fora de propósito: a demo convida o visitante a
    CRIAR uma OS e ver o fluxo (link do cliente, financeiro, relatórios) se preencher.
    """
    if not _base_vazia(db):
        return

    for codigo, desc, un, custo, venda, atual, minimo, local in PECAS:
        db.execute(
            """INSERT INTO peca (codigo, descricao, unidade, preco_custo, preco_venda,
                                 estoque_atual, estoque_minimo, localizacao)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (codigo, desc, un, custo, venda, atual, minimo, local),
        )

    ids = []
    for c in CLIENTES:
        cur = db.execute(
            """INSERT INTO cliente
                   (razao_social, nome_fantasia, cpf_cnpj, email, telefone1,
                    cep, logradouro, numero, bairro, cidade, uf, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10], None),
        )
        ids.append(cur.lastrowid)

    for idx_cli, patrimonio, modelo, marca, serie in EQUIPAMENTOS:
        if patrimonio:
            db.execute(
                """INSERT INTO equipamento (id_cliente, patrimonio, modelo, marca, numero_serie)
                   VALUES (?, ?, ?, ?, ?)""",
                (ids[idx_cli], patrimonio, modelo, marca, serie),
            )
        else:
            cur = db.execute(
                """INSERT INTO equipamento (id_cliente, patrimonio, modelo, marca, numero_serie)
                   VALUES (?, ?, ?, ?, ?)""",
                (ids[idx_cli], f"__tmp_{idx_cli}_{modelo[:4]}", modelo, marca, serie),
            )
            db.execute("UPDATE equipamento SET patrimonio = ? WHERE id = ?",
                       (f"ESG{cur.lastrowid}", cur.lastrowid))

    db.commit()


def preparar_demo() -> None:
    """Boot (dentro de app_context): só roda em MODO_DEMO.

    Garante que o acesso de demo entra sem forçar troca de senha (a senha é pública
    de propósito; forçar troca deixaria o 1º visitante trancar os demais) e semeia
    os dados de exemplo na primeira subida.
    """
    if not modo_demo():
        return
    db = get_db()
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    if email:
        db.execute(
            "UPDATE usuario SET precisa_trocar_senha = 0 WHERE lower(email) = ? AND D_E_L_E_T = 0",
            (email,),
        )
        db.commit()
    semear_demo(db)


def reiniciar_demo() -> None:
    """Zera os dados de negócio e devolve o estado de exemplo. Só em MODO_DEMO.

    Preserva perfis/módulos/permissões/configuração e o usuário admin de demo.
    """
    if not modo_demo():
        return
    db = get_db()
    db.commit()                               # fecha qualquer transação aberta
    db.execute("PRAGMA foreign_keys = OFF")   # some com a ordem de dependência no apagar
    tabelas = [
        r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for t in tabelas:
        if t not in _PRESERVAR:
            db.execute(f"DELETE FROM {t}")
    # zera o AUTOINCREMENT das tabelas apagadas, pras novas linhas começarem do 1
    db.execute(
        "DELETE FROM sqlite_sequence WHERE name NOT IN (%s)" % ",".join("?" * len(_PRESERVAR)),
        tuple(_PRESERVAR),
    )
    db.commit()
    db.execute("PRAGMA foreign_keys = ON")
    semear_demo(db)
    preparar_demo()


def init_demo(app) -> None:
    """Deixa `modo_demo` e `demo_cred` disponíveis em todos os templates."""
    @app.context_processor
    def _ctx():
        return {"modo_demo": modo_demo(), "demo_cred": credenciais_demo()}
