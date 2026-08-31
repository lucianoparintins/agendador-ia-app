import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB_PATH, _connect


def main() -> None:
    resposta = input(
        f"Zerar o banco '{DB_PATH}'? Esta ação apaga todos os dados. [s/N] "
    ).strip().lower()
    if resposta not in ("s", "sim"):
        print("Operação cancelada.")
        return

    with _connect() as conn:
        conn.executescript(
            "DELETE FROM agendamentos; "
            "DELETE FROM mensagens; "
            "DELETE FROM sessoes; "
        )
        conn.execute("DELETE FROM sqlite_sequence;")

    print("Banco zerado.")


if __name__ == "__main__":
    main()
