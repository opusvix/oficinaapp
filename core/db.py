"""Conexão e helpers do banco SQLite."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from flask import current_app, g


def get_db() -> sqlite3.Connection:
    """Retorna conexão do banco (uma por request).

    Sem detect_types=PARSE_DECLTYPES: o conversor padrão de TIMESTAMP é
    deprecated no 3.12 e removido no 3.14. Aqui tudo volta como str, e a
    comparação de data se faz por coluna INTEGER epoch quando importa.
    """
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e: Optional[BaseException] = None) -> None:
    """Fecha conexão ao fim do request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Cria tabelas e dados base se não existirem (idempotente)."""
    db = get_db()
    base = Path(current_app.root_path)
    for nome in ("schema.sql", "seed.sql"):
        schema_path = base / "scripts" / nome
        if schema_path.exists():
            with open(schema_path, encoding="utf-8") as f:
                db.executescript(f.read())
            db.commit()
    _migracoes(db)


def _migracoes(db: sqlite3.Connection) -> None:
    """Colunas novas em tabelas já existentes (CREATE IF NOT EXISTS não altera).

    Cada entrada: (tabela, coluna, DDL). Guardado por PRAGMA table_info —
    rodar duas vezes não duplica nada.
    """
    pendentes = [
        ("cliente", "foto", "foto VARCHAR(255)"),
        ("ordem_servico", "testado_funcionamento",
         "testado_funcionamento SMALLINT NOT NULL DEFAULT 0"),
        ("ordem_servico", "entrega_solicitada_em", "entrega_solicitada_em TIMESTAMP"),
        # Fase 7: títulos a pagar/receber
        ("financeiro", "id_cliente", "id_cliente INTEGER REFERENCES cliente(id)"),
        ("financeiro", "fornecedor", "fornecedor VARCHAR(200)"),
        ("financeiro", "id_origem", "id_origem INTEGER"),          # título que foi parcelado
        ("financeiro", "usuario_baixa", "usuario_baixa INTEGER"),
        ("financeiro", "id_caixa", "id_caixa INTEGER"),
    ]
    for tabela, coluna, ddl in pendentes:
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({tabela})")}
        if coluna not in cols:
            db.execute(f"ALTER TABLE {tabela} ADD COLUMN {ddl}")

    # Orçamento = soma dos itens (os.recalcula_orcamento). Idempotente: alinha as
    # OS que AINDA esperam aprovação. Aprovada/recusada/entregue mantêm o valor
    # que o cliente viu: é o registro do combinado e não se reescreve.
    db.execute(
        """UPDATE ordem_servico
              SET orcamento_valor = (SELECT COALESCE(SUM(i.subtotal), 0) FROM item_os i
                                      WHERE i.id_os = ordem_servico.id AND i.D_E_L_E_T = 0)
            WHERE status IN ('aberta', 'avaliacao') AND D_E_L_E_T = 0"""
    )
    db.commit()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Context manager para transação com commit/rollback automático."""
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Executa SQL e retorna cursor."""
    return get_db().execute(sql, params)


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Executa SELECT e retorna todas as linhas."""
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    """Executa SELECT e retorna uma linha ou None."""
    return get_db().execute(sql, params).fetchone()


def execute_many(sql: str, params_list: list[tuple]) -> None:
    """Executa múltiplas inserções/atualizações."""
    db = get_db()
    db.executemany(sql, params_list)
    db.commit()