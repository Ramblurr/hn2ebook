from datetime import datetime
import click
from hn2epub import core
from hn2epub.misc.log import logger

log = logger.get_logger("commands")


def default_meta(pub_date):
    return {
        "identifier": f"hn2epub-{pub_date}",
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


def check_writable(path):
    try:
        f = open(path, "w")
        f.close()
    except:
        raise click.BadParameter(f"cannot write to output path {path}")


def epub_from_posts(ctx, post_ids, output, pub_date):
    check_writable(output)
    meta = default_meta(pub_date)
    log.info("starting generation of epub for post ids %s" % (",".join(post_ids)))
    core.epub_from_posts(ctx.cfg["hn2epub"], post_ids, meta, output)


def epub_from_range(ctx, date_range, output, limit):
    check_writable(output)
    meta = default_meta(date_range[1].isoformat())
    log.info(f"fetching posts {date_range}")
    post_ids = core.find_posts(date_range)
    if limit:
        post_ids = post_ids[0 : min(limit, len(post_ids))]
    log.info("starting generation of epub for post ids %s" % (",".join(post_ids)))
    core.epub_from_posts(ctx.cfg["hn2epub"], post_ids, meta, output)
