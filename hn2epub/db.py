import sqlite3
import json

# a global connection .. oh my
# conn = None


# def _conn_check():
#    if not conn:
#        raise ValueError("the system is not connected to the sqlite database.")


def connect(db_path):
    global conn
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def disconnect(db_path):
    global conn
    if conn:
        conn.close()
        conn = None


def insert_best_stories(conn, tuples):
    conn.executemany(
        "INSERT OR IGNORE INTO hn_best_story (item_id, day) VALUES (?, ?)", tuples
    )


def all_best_stories(conn):
    cur = conn.cursor()
    return cur.execute(
        "SELECT item_id, day from hn_best_story ORDER BY day DESC"
    ).fetchall()


def best_stories_for(conn, start_date, end_date):
    """
    Returns the best story ids between [start,end)
    """
    cur = conn.cursor()
    return cur.execute(
        "SELECT item_id, day from hn_best_story WHERE day >= ? AND day < ? ORDER BY day DESC",
        (start_date, end_date),
    ).fetchall()


def insert_book(conn, book, post_ids):
    payload = {
        "uuid": book["uuid"],
        "at": book["at"],
        "num_items": book["num_items"],
        "meta": json.dumps(book["meta"]),
    }
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO generated_book (uuid, at, num_items, meta) VALUES (:uuid, :at, :num_items, :meta)",
        payload,
    )
    book_id = cur.lastrowid
    item_books = [(book_id, post_id) for post_id in post_ids]
    cur.executemany(
        "INSERT OR IGNORE INTO item_book (book_id, item_id) VALUES (?, ?)", item_books
    )


def parse_book(row):
    o = dict(row)
    print(o)
    o["meta"] = json.loads(o["meta"])
    return o


def all_books(conn):
    cur = conn.cursor()
    raw = cur.execute("SELECT * FROM generated_book ORDER BY at DESC").fetchall()
    return [parse_book(book) for book in raw]
