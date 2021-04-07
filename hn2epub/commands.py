from uuid import uuid4

import click
import requests_cache

from pathlib import Path
from datetime import datetime, timedelta

from hn2epub import core
from hn2epub import hn
from hn2epub import db
from hn2epub.misc.log import logger

log = logger.get_logger("commands")

requests_cache.install_cache("hn2epub")


def atommeta():
    return {
        "creation_params": metadata["creation_params"],
        "title": metadata["title"],
        "id": metadata["identifier"],
        "atom_timestamp": metadata["DC"]["date"],
        "authors": [{"name": name} for name in metadata["authors"]],
        "publishers": [{"name": metadata["DC"]["publisher"]}],
        "language": metadata["language"],
        "summary": metadata["DC"]["description"],
        "has_cover": False,
        "cover_url": "",
        "formats": [
            {
                "url": f"{root_url}/books/{file_name}",
                "size": file_size,
                "mimetype": "application/epub+zip",
            }
        ],
    }


def _stored_meta(epub_path_name, metadata):
    epub_path = Path(epub_path_name)
    file_name = epub_path.name
    file_size = epub_path.stat().st_size
    metadata["formats"] = [
        {
            "file_name": file_name,
            "file_size": file_size,
            "mimetype": "application/epub+zip",
        }
    ]
    return metadata


def _persist_epub_meta(conn, uuid, at, posts, metadata, epub_path_name):
    post_ids = [post["id"] for post in posts]
    final_meta = _stored_meta(epub_path_name, metadata)
    book = {"uuid": uuid, "at": at, "meta": final_meta, "num_items": len(post_ids)}
    db.insert_book(conn, book, post_ids)


def _default_meta(pub_date, identifer_suffix):
    identifier = f"hn2epub;{pub_date};{identifer_suffix}"
    return {
        "identifier": identifier,
        "title": "Hacker News Weekly",
        "authors": ["hn2epub"],
        "language": "en",
        "DC": {
            "description": "Hacker News Weekly digest for the week of",
            "subject": "News",
            "date": pub_date,
            "publisher": "hn2epub",
        },
    }


def _check_writable(path):
    try:
        f = open(path, "w")
        f.close()
    except:
        raise click.BadParameter(f"cannot write to output path {path}")


def epub_from_posts(ctx, post_ids, output, pub_date):
    cfg = ctx.cfg["hn2epub"]
    uuid = str(uuid4())
    now = datetime.utcnow()
    now_iso = now.isoformat()
    output = get_output_path(cfg, user_output, now_iso)

    _check_writable(output)

    post_ids_str = ",".join(post_ids)
    meta = _default_meta(pub_date, post_ids_str)
    log.info("starting generation of epub for post ids %s" % (post_ids_str))
    meta["num_posts"] = len(post_ids)

    meta["creation_params"] = {"post_ids": post_ids}
    epub_path = core.epub_from_posts(cfg, post_ids, meta, output)


def get_output_path(cfg, user_output, now_iso):
    books_path = Path(cfg["data_dir"]).joinpath("books")
    if not user_output:
        output = books_path.joinpath(f"hn2epub-{now_iso}.epub")
    else:
        output = user_output
    return output


def posts_for_range(cfg, conn, date_range, limit, criteria):
    post_ids = [
        post_id
        for post_id, _ in db.best_stories_for(conn, date_range[0], date_range[1])
    ]
    return core.resolve_posts(cfg, post_ids, limit, criteria)


def epub_from_range(ctx, date_range, user_output, limit, criteria, persist):
    cfg = ctx.cfg["hn2epub"]
    uuid = str(uuid4())
    now = datetime.utcnow()
    now_iso = now.isoformat()
    if user_output:
        persist = False

    output = get_output_path(cfg, user_output, now_iso)
    _check_writable(output)

    date_range_str = [date_range[0].isoformat(), date_range[1].isoformat()]

    log.info(f"fetching posts for range {date_range_str}")
    conn = db.connect("/var/home/ramblurr/src/hn2epub/dev.sqlite")
    posts = posts_for_range(cfg, conn, date_range, limit, criteria)
    conn.close()

    suffix = "-".join(date_range_str)
    meta = _default_meta(now_iso, suffix)
    log.info("starting generation of epub for %d posts" % len(posts))
    meta["num_posts"] = len(posts)
    meta["creation_params"] = {"date_range": date_range_str, "limit": limit}
    epub_path = core.epub_from_posts(cfg, posts, meta, output)

    if persist:
        conn = db.connect("/var/home/ramblurr/src/hn2epub/dev.sqlite")
        with conn:
            _persist_epub_meta(conn, uuid, now, posts, meta, epub_path)


def generate_opds(ctx):
    with shelve.open(ctx.db_path) as db:
        core.generate_opds(ctx.cfg["hn2epub"], db)


def list_entries(ctx):

    import pprint

    pp = pprint.PrettyPrinter(indent=2)
    with shelve.open(ctx.db_path) as db:
        entries = db.get("entries", {})
        entries = sorted(entries.values(), key=lambda k: k["creation_params"]["at"])
        log.info("Entries")
        for entry in entries:
            log.info(pp.pformat(entry))


def update_best(ctx):
    conn = db.connect("/var/home/ramblurr/src/hn2epub/dev.sqlite")
    day = datetime.utcnow().date()
    with conn:
        hn.update_best_stories(conn, day)


def backfill_best(ctx):
    conn = db.connect("/var/home/ramblurr/src/hn2epub/dev.sqlite")
    start_day = datetime.utcnow().date() - timedelta(days=30)
    end_day = datetime.utcnow().date()
    with conn:
        hn.backfill_daemonology(conn, start_day, end_day)
