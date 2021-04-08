import sys
import sqlite3
import json
from pathlib import Path
from itertools import groupby

from hn2epub.misc.log import logger
from yoyo import get_backend
from yoyo import read_migrations

log = logger.get_logger("db")


def yoyo_context(db_path):
    backend_uri = f"sqlite:///{db_path}"
    migrations_path = Path(__file__).parent / "migrations"
    backend = get_backend(backend_uri)
    migrations = read_migrations(str(migrations_path))
    log.debug(f"loaded yoyo db context {backend_uri} from {migrations_path}")
    return backend, migrations


def needs_migration(db_path):
    backend, migrations = yoyo_context(db_path)
    applied = backend.to_rollback(migrations)
    return len(migrations) != len(applied)


def migrate(db_path):
    backend, migrations = yoyo_context(db_path)
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


def select_keys(d, keys):
    return {k: d[k] for k in keys}


def connect(db_path):
    if needs_migration(db_path):
        log.error(f"ERROR: database {db_path} needs to be migrated")
        sys.exit(2)

    conn = sqlite3.connect(db_path)
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    return conn


def insert_best_stories(conn, tuples):
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO hn_best_story (story_id, day) VALUES (?, ?)", tuples
    )
    return cur.rowcount


def all_best_stories(conn):
    cur = conn.cursor()
    return [
        dict(row)
        for row in cur.execute(
            "SELECT story_id, day from hn_best_story ORDER BY day DESC"
        ).fetchall()
    ]


def best_stories_for(conn, start_date, end_date):
    """
    Returns the best story ids between [start,end)
    """
    cur = conn.cursor()
    return cur.execute(
        "SELECT story_id, day from hn_best_story WHERE day >= ? AND day < ? ORDER BY day DESC",
        (start_date, end_date),
    ).fetchall()


def insert_book(conn, book, post_ids, formats, period):
    payload = {
        "uuid": book["uuid"],
        "at": book["at"],
        "num_stories": book["num_stories"],
        "meta": json.dumps(book["meta"]),
        "period": period,
    }
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cur.execute(
            "INSERT INTO generated_book (uuid, at, num_stories, meta, period) VALUES (:uuid, :at, :num_stories, :meta, :period)",
            payload,
        )
        book_id = cur.lastrowid
        formats_payload = [
            (book_id, f["file_name"], f["file_size"], f["mimetype"]) for f in formats
        ]
        cur.executemany(
            "INSERT INTO generated_book_format (book_id, file_name, file_size, mimetype) VALUES (?, ?, ?, ?)",
            formats_payload,
        )
        story_books = [(book_id, post_id) for post_id in post_ids]
        cur.executemany(
            "INSERT OR IGNORE INTO story_book (book_id, story_id) VALUES (?, ?)",
            story_books,
        )
        cur.execute("COMMIT")
    except conn.Error as e:
        log.error(e)
        cur.execute("ROLLBACK")


def _post_books(raw):
    book_rows = [dict(book) for book in raw]
    books = {}
    for k, g in groupby(book_rows, key=lambda t: t["book_id"]):
        rows = list(g)
        book = select_keys(
            rows[0], ["id", "uuid", "at", "num_stories", "meta", "period"]
        )
        book["formats"] = [
            select_keys(row, ["file_name", "file_size", "mimetype"]) for row in rows
        ]
        book["meta"] = json.loads(book["meta"])
        books[k] = book
    return books.values()


def all_books(conn):
    cur = conn.cursor()
    raw = cur.execute(
        "SELECT * FROM generated_book b INNER JOIN generated_book_format f on f.book_id = b.id ORDER BY at DESC"
    ).fetchall()
    return _post_books(raw)


def books_by_period(conn, period):
    cur = conn.cursor()
    q = "SELECT * FROM generated_book b INNER JOIN generated_book_format f on f.book_id = b.id WHERE b.period = ? ORDER BY at DESC"
    print(q, period)
    raw = cur.execute(q, (period,),).fetchall()
    return _post_books(raw)
