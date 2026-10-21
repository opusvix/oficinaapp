"""Dados de demonstração (só dev): clientes + equipamentos.

Roda uma vez por banco novo:
    .venv\\Scripts\\python.exe scripts\\dados_demo.py

Gera CPF/CNPJ com dígito verificador de verdade — se o Pydantic do app
rejeitar, o teste de fumaça falha aqui primeiro, não no navegador.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from core.db import get_db  # noqa: E402


def _verificador(base: str, pesos: list[int]) -> str:
    soma = sum(int(base[i]) * pesos[i] for i in range(len(pesos)))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cpf_valido(base9: str) -> str:
    d1 = _verificador(base9, [10, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _verificador(base9 + d1, [11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
    return base9 + d1 + d2


def cnpj_valido(base12: str) -> str:
    d1 = _verificador(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _verificador(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base12 + d1 + d2


CLIENTES = [
    # razao, fantasia, doc, email, tel, cep, logradouro, numero, bairro, cidade, uf
    ("Padaria São Jorge Ltda", "Padaria São Jorge", cnpj_valido("112223330001"),
     "contato@padariasaojorge.com.br", "1133334444", "01310100",
     "Av. Paulista", "1500", "Bela Vista", "São Paulo", "SP"),
    ("Mercado Bom Preço Eireli", "Bom Preço", cnpj_valido("223334440001"),
     "fiscal@mercadobompreco.com.br", "1134445555", "03015000",
     "Rua do Oratório", "210", "Mooca", "São Paulo", "SP"),
    ("Restaurante Sabor da Terra", None, cpf_valido("123456789"),
     "sabordaterra@gmail.com", "11988887777", "04038000",
     "Rua Gaivota", "88", "Saúde", "São Paulo", "SP"),
    ("Clínica Odonto Bem Sorriso", "Bem Sorriso", cnpj_valido("334445550001"),
     "recepcao@bemsorriso.com.br", "1135556666", "04571010",
     "Av. Brigadeiro Luís Antônio", "2000", "Jardim América", "São Paulo", "SP"),
    ("Lanchonete do Zé", None, cpf_valido("987654321"),
     None, "11977776666", "02011000",
     "Rua Voluntários da Pátria", "305", "Santana", "São Paulo", "SP"),
    ("Supermercado Estrela do Norte Ltda", "Estrela do Norte",
     cnpj_valido("445556660001"), "compras@estreladonorte.com.br",
     "1136667777", "07034000", "Av. Marechal Tito", "900", "Vila Gomes Cardim",
     "Guarulhos", "SP"),
    ("Hamburgueria Fogo Alto", "Fogo Alto", cnpj_valido("556667770001"),
     "oi@fogoalto.com.br", "11966665555", "04094000",
     "Rua Borges de Medeiros", "45", "Moema", "São Paulo", "SP"),
    ("Escola Aprender e Crescer", None, cnpj_valido("667778880001"),
     "direcao@aprenderecrescer.edu.br", "1137778888", "05508000",
     "Rua Giovani Gronchi", "1200", "Campo Limpo", "São Paulo", "SP"),
]

EQUIPAMENTOS = [
    # indice do cliente, patrimonio ("" = gera ESG{id}), modelo, marca, serie
    (0, "ESG101", "Freezer horizontal 300L", "Electrolux", "FX30A91"),
    (0, "ESG102", "Batedeira planetária 10L", "KitchenAid", "KP10WH"),
    (1, "ESG103", "Câmara fria 1 porta", "Metral", "CF1P22"),
    (1, "ESG104", "Expositor de doces 90cm", "Inbrás", "EXD90"),
    (2, "ESG105", "Fogão 6 bocas industrial", "Séries", "F6BIND"),
    (2, "", "Liquidificador 2L", "Mondial", "ML2FE"),   # Tag em branco -> ESG{id}
    (3, "ESG107", "Esterilizador autoclave", "Cristófoli", "AC12B"),
    (4, "ESG108", "Chapa elétrica 80cm", "Lion", "CH80EL"),
    (5, "ESG109", "Serra fria automática", "Bosch", "GKS190"),
    (5, "ESG110", "Compressor de ar 50L", "Schulz", "CFA50"),
    (6, "", "Fritadeira industrial 25L", "Lion", "FR25IN"),  # Tag em branco
    (7, "ESG112", "Bebedouro de bancada", "Crystal", "BBDB10"),
]


def main() -> int:
    app = create_app()
    with app.app_context():
        db = get_db()
        if db.execute("SELECT COUNT(*) FROM cliente WHERE D_E_L_E_T = 0").fetchone()[0]:
            print("JA EXISTEM CLIENTES — nada a fazer.")
            return 0

        ids = []
        for c in CLIENTES:
            cur = db.execute(
                """INSERT INTO cliente
                       (razao_social, nome_fantasia, cpf_cnpj, email, telefone1,
                        cep, logradouro, numero, bairro, cidade, uf, observacoes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9],
                 c[10], None),
            )
            ids.append(cur.lastrowid)

        geradas = 0
        for idx_cli, patrimonio, modelo, marca, serie in EQUIPAMENTOS:
            if patrimonio:
                db.execute(
                    """INSERT INTO equipamento
                           (id_cliente, patrimonio, modelo, marca, numero_serie)
                       VALUES (?, ?, ?, ?, ?)""",
                    (ids[idx_cli], patrimonio, modelo, marca, serie),
                )
            else:
                cur = db.execute(
                    """INSERT INTO equipamento
                           (id_cliente, patrimonio, modelo, marca, numero_serie)
                       VALUES (?, ?, ?, ?, ?)""",
                    (ids[idx_cli], f"__tmp_{geradas}", modelo, marca, serie),
                )
                db.execute("UPDATE equipamento SET patrimonio = ? WHERE id = ?",
                           (f"ESG{cur.lastrowid}", cur.lastrowid))
                geradas += 1

        db.commit()
        print(f"OK {len(CLIENTES)} clientes e {len(EQUIPAMENTOS)} equipamentos "
              f"({geradas} com Tag gerada pelo backend).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
