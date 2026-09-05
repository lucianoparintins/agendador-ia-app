import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

from dateutil import parser as dateutil_parser

DB_PATH = Path(__file__).resolve().parent / "agendamento.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mensagens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    FOREIGN KEY (sessao_id) REFERENCES sessoes (id)
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    telefone TEXT UNIQUE NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agendamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id INTEGER NOT NULL,
    cliente_id INTEGER,
    servico TEXT,
    data TEXT,
    hora TEXT,
    status TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    FOREIGN KEY (sessao_id) REFERENCES sessoes (id),
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _tx():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def criar_sessao(titulo: str) -> int:
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO sessoes (titulo, criado_em) VALUES (?, ?)",
            (titulo, _now()),
        )
        return cur.lastrowid


def listar_sessoes():
    with _tx() as conn:
        rows = conn.execute("SELECT * FROM sessoes ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def obter_sessao(sessao_id: int):
    with _tx() as conn:
        row = conn.execute("SELECT * FROM sessoes WHERE id = ?", (sessao_id,)).fetchone()
        return dict(row) if row else None


def adicionar_mensagem(sessao_id: int, role: str, conteudo: str) -> int:
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO mensagens (sessao_id, role, conteudo, criado_em) VALUES (?, ?, ?, ?)",
            (sessao_id, role, conteudo, _now()),
        )
        return cur.lastrowid


def listar_mensagens(sessao_id: int):
    with _tx() as conn:
        rows = conn.execute(
            "SELECT * FROM mensagens WHERE sessao_id = ? ORDER BY id", (sessao_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def criar_cliente(nome: str, telefone: str) -> int:
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO clientes (nome, telefone, criado_em) VALUES (?, ?, ?)",
            (nome, telefone, _now()),
        )
        return cur.lastrowid


def obter_cliente_por_telefone(telefone: str):
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM clientes WHERE telefone = ?", (telefone,)
        ).fetchone()
        return dict(row) if row else None


def obter_cliente(cliente_id: int):
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
        ).fetchone()
        return dict(row) if row else None


def listar_clientes():
    with _tx() as conn:
        rows = conn.execute("SELECT * FROM clientes ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def atualizar_cliente(cliente_id: int, nome: str, telefone: str) -> None:
    with _tx() as conn:
        conn.execute(
            "UPDATE clientes SET nome = ?, telefone = ? WHERE id = ?",
            (nome, telefone, cliente_id),
        )


def remover_cliente(cliente_id: int) -> None:
    with _tx() as conn:
        conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))


def obter_rascunho_ativo(sessao_id: int) -> Optional[dict]:
    with _tx() as conn:
        row = conn.execute(
            """SELECT * FROM agendamentos
               WHERE sessao_id = ? AND status = 'rascunho'
               ORDER BY id DESC LIMIT 1""",
            (sessao_id,),
        ).fetchone()
        return dict(row) if row else None


def atualizar_agendamento(
    agendamento_id: int, cliente_id, servico, data, hora, status
) -> None:
    with _tx() as conn:
        conn.execute(
            """UPDATE agendamentos
               SET cliente_id = ?, servico = ?, data = ?, hora = ?, status = ?, criado_em = ?
               WHERE id = ?""",
            (cliente_id, servico, data, hora, status, _now(), agendamento_id),
        )


def salvar_agendamento(sessao_id: int, cliente_id, servico, data, hora, status="rascunho") -> int:
    rascunho = obter_rascunho_ativo(sessao_id)
    if rascunho is not None:
        campos = (
            ("cliente_id", cliente_id),
            ("servico", servico),
            ("data", data),
            ("hora", hora),
        )
        merged = dict(rascunho)
        for chave, valor in campos:
            if valor:
                merged[chave] = valor
        atualizar_agendamento(
            rascunho["id"],
            merged["cliente_id"],
            merged["servico"],
            merged["data"],
            merged["hora"],
            status,
        )
        return rascunho["id"]

    with _tx() as conn:
        cur = conn.execute(
            """INSERT INTO agendamentos (sessao_id, cliente_id, servico, data, hora, status, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sessao_id, cliente_id, servico, data, hora, status, _now()),
        )
        return cur.lastrowid


def salvar_agendamento_rejeitado(sessao_id: int, cliente_id, servico, data, hora) -> int:
    with _tx() as conn:
        cur = conn.execute(
            """INSERT INTO agendamentos (sessao_id, cliente_id, servico, data, hora, status, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sessao_id, cliente_id, servico, data, hora, "rejeitado", _now()),
        )
        return cur.lastrowid


def verificar_conflito(data: str, hora_inicio: str, hora_fim: str) -> bool:
    alvo_data = _data_iso(data)
    if alvo_data is None:
        return False
    with _tx() as conn:
        rows = conn.execute(
            """SELECT data, hora FROM agendamentos
               WHERE status = 'confirmado' AND data IS NOT NULL AND hora IS NOT NULL"""
        ).fetchall()
    for r in rows:
        if _data_iso(r["data"]) != alvo_data:
            continue
        if _sobrepoe(hora_inicio, hora_fim, r["hora"]):
            return True
    return False


def _data_iso(texto) -> Optional[str]:
    try:
        return dateutil_parser.parse(str(texto), dayfirst=True).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _sobrepoe(inicio_a: str, fim_a: str, inicio_b: str) -> bool:
    h1 = _hora(inicio_a)
    h2 = _hora(inicio_b)
    if h1 is None or h2 is None:
        return False
    fim1 = (datetime.combine(datetime.min.date(), h1) + timedelta(minutes=60)).time()
    fim2 = (datetime.combine(datetime.min.date(), h2) + timedelta(minutes=60)).time()
    return h1 < fim2 and h2 < fim1


def _hora(texto) -> Optional[time]:
    try:
        return dateutil_parser.parse(str(texto)).time()
    except (ValueError, TypeError, OverflowError):
        return None


def listar_agendamentos():
    with _tx() as conn:
        rows = conn.execute(
            """SELECT a.id, a.sessao_id, a.cliente_id, c.nome AS cliente,
                      c.telefone AS telefone, a.servico, a.data, a.hora, a.status,
                      a.criado_em
               FROM agendamentos a
               LEFT JOIN clientes c ON c.id = a.cliente_id
               ORDER BY a.id"""
        ).fetchall()
        return [dict(r) for r in rows]
