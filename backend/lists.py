"""Notas y lista de la compra por voz. Se guardan en la tabla list_items de jarvis.db."""
from database import get_db


def _ensure():
    db = get_db()
    db.execute(
        "CREATE TABLE IF NOT EXISTS list_items ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " list_name TEXT NOT NULL,"
        " item TEXT NOT NULL,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    db.commit()
    db.close()


def add_item(list_name: str, item: str):
    _ensure()
    db = get_db()
    db.execute("INSERT INTO list_items (list_name, item) VALUES (?, ?)", (list_name, item))
    db.commit()
    db.close()


def read_items(list_name: str):
    _ensure()
    db = get_db()
    rows = db.execute("SELECT item FROM list_items WHERE list_name = ? ORDER BY id",
                      (list_name,)).fetchall()
    db.close()
    return [r["item"] for r in rows]


def clear_list(list_name: str) -> int:
    _ensure()
    db = get_db()
    n = db.execute("SELECT COUNT(*) AS c FROM list_items WHERE list_name = ?",
                   (list_name,)).fetchone()["c"]
    db.execute("DELETE FROM list_items WHERE list_name = ?", (list_name,))
    db.commit()
    db.close()
    return n


def remove_item(list_name: str, item: str) -> int:
    _ensure()
    db = get_db()
    cur = db.execute("DELETE FROM list_items WHERE list_name = ? AND item LIKE ?",
                     (list_name, f"%{item}%"))
    db.commit()
    n = cur.rowcount
    db.close()
    return n
