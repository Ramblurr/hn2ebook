from uuid import uuid4

import click
import requests_cache

from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

from hn2epub import core
from hn2epub import hn
from hn2epub import db
from hn2epub.misc.log import logger

log = logger.get_logger("commands")

requests_cache.install_cache("hn2epub")


def isoformat(d):
    return d.isoformat() + "Z"


def _persist_epub_meta(conn, at, stories, meta, epub_path_name, period):
    story_ids = [story["id"] for story in stories]

    assert len(story_ids) == meta["num_stories"]

    book = {
        "uuid": meta["uuid"],
        "at": at,
        "meta": meta,
        "num_stories": meta["num_stories"],
    }

    epub_path = Path(epub_path_name)
    file_name = epub_path.name
    file_size = epub_path.stat().st_size
    formats = [
        {
            "file_name": file_name,
            "file_size": file_size,
            "mimetype": "application/epub+zip",
        }
    ]

    db.insert_book(conn, book, story_ids, formats, period)


def format_range(start_or_date_range, end=None):
    if not end:
        start, end = start_or_date_range
    else:
        start = start_or_date_range
    start_str, end_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    if not end:
        return [start_str, end_str]
    return start_str, end_str


def epub_title(params):
    if "period" in params:
        period = params["period"]
        period_name = period.title()
        title = f"Hacker News {period_name}"

        if period == "daily":
            subtitle = params["as_of"].strftime("for the day of %a, %d %b, %Y")
        elif period == "weekly":
            subtitle = params["as_of"].strftime("for week %V of %Y")
        elif period == "monthly":
            subtitle = params["as_of"].strftime("for the month of %B %Y")
    elif "start" in params:
        start = params["start"]
        end = params["end"]
        title = f"Hacker News Digest"
        subtitle = "for %s to %s" % format_range(start, end)
    elif "story_ids" in params:
        title = f"Hacker News Series"
        subtitle = "the finest %d hand-picked stories" % (len(params["story_ids"]))

    return title, subtitle


def epub_headlines(stories):
    headlines = []
    for story in stories:
        title = story["title"]
        headlines.append(title)
    return headlines


def issue_meta(stories, creation_params, pub_date, uuid):
    title, subtitle = epub_title(creation_params)
    headlines_list = epub_headlines(stories)
    return {
        "title": title,
        "subtitle": subtitle,
        "num_stories": len(stories),
        "identifier": "urn:uuid:%s" % uuid,
        "uuid": uuid,
        "authors": ["hn2epub"],
        "language": "en",
        "headlines": headlines_list,
        "DC": {"subject": "News", "date": pub_date, "publisher": "hn2epub",},
    }


def check_writable(path):
    try:
        f = open(path, "w")
        f.close()
    except:
        raise click.BadParameter(f"cannot write to output path {path}")


def get_output_path(cfg, user_output, suffix):
    books_path = Path(cfg["data_dir"]).joinpath("books")
    if not user_output:
        output = books_path.joinpath(f"hn2epub-{suffix}.epub")
    else:
        output = user_output
    check_writable(output)
    return output


def stories_for_range(cfg, conn, date_range, limit, criteria):
    story_ids = [
        story_id
        for story_id, _ in db.best_stories_for(
            conn, date_range[0].date(), date_range[1].date()
        )
    ]
    return core.resolve_stories(cfg, story_ids, limit, criteria)


def collect_stories(cfg, date_range, limit, criteria):
    log.info("collecting stories for range %s - %s" % format_range(date_range))
    conn = db.connect(cfg["db_path"])
    stories = stories_for_range(cfg, conn, date_range, limit, criteria)
    conn.close()
    return stories


period_to_delta = {
    "weekly": "weeks",
    "daily": "days",
    "monthly": "months",
}


def range_for_period(as_of, period):
    kwargs = {period_to_delta[period]: 1}
    start = as_of - relativedelta(**kwargs)
    end = as_of + relativedelta(days=1)
    return [start, end]


def new_issue(ctx, period_or_range, as_of, user_output, limit, criteria, persist):
    cfg = ctx.cfg["hn2epub"]
    now = datetime.utcnow()

    if period_or_range in period_to_delta:
        period = period_or_range
        log.info(
            "creating %s periodical as of %s, with limit=%s, sort_criteria=%s"
            % (period, as_of, limit, criteria)
        )
        date_range = range_for_period(as_of, period)
        end_str = str(as_of.date())
        output = get_output_path(cfg, user_output, f"{period}-{end_str}")
        creation_params = {
            "period": period,
            "as_of": as_of,
            "limit": limit,
            "criteria": criteria,
        }

    else:
        log.info(
            "creating periodical with range %s, with limit=%s, sort_criteria=%s"
            % (date_range, limit, criteria)
        )
        date_range = period_or_range
        output = get_output_path(
            cfg, user_output, "%s-%s" % (date_range[0], date_range[1])
        )
        creation_params = {
            "start": date_range[0],
            "end": date_range[1],
            "limit": limit,
            "criteria": criteria,
        }
        period = "custom"

    stories = collect_stories(cfg, date_range, limit, criteria)
    log.info("collected %d stories for the issue" % len(stories))
    meta = issue_meta(stories, creation_params, isoformat(now), str(uuid4()))

    epub_path = core.epub_from_stories(cfg, stories, meta, output)

    if persist:
        with db.connect(cfg["db_path"]) as conn:
            _persist_epub_meta(conn, now, stories, meta, epub_path, period)


def new_custom_issue(ctx, story_ids, user_output, criteria):
    cfg = ctx.cfg["hn2epub"]
    now = datetime.utcnow()
    check_writable(user_output)

    creation_params = {
        "story_ids": story_ids,
        "criteria": criteria,
    }

    stories = core.resolve_stories(cfg, story_ids, 9999, criteria)
    meta = issue_meta(stories, creation_params, isoformat(now), str(uuid4()))
    epub_path = core.epub_from_stories(cfg, stories, meta, user_output)


def generate_opds(ctx):
    cfg = ctx.cfg["hn2epub"]
    conn = db.connect(cfg["db_path"])

    instance = {
        "root_url": cfg["root_url"],
        "name": cfg["instance_name"],
        "url": "/index.xml",
    }
    feeds = [
        {
            "period": "daily",
            "name": "Hacker News Daily",
            "url": f"/daily.xml",
            "up_url": f"/index.xml",
            "start_url": f"/index.xml",
            "content": "Daily periodicals of the best articles on Hacker News",
        },
        {
            "period": "weekly",
            "name": "Hacker News Weekly",
            "url": f"/weekly.xml",
            "up_url": f"/index.xml",
            "start_url": f"/index.xml",
            "content": "Weekly periodicals of the best articles on Hacker News",
        },
        {
            "period": "monthly",
            "name": "Hacker News Monthly",
            "url": f"/monthly.xml",
            "up_url": f"/index.xml",
            "start_url": f"/index.xml",
            "content": "Monthly periodicals of the best articles on Hacker News",
        },
    ]

    for feed in feeds:
        core.generate_opds(
            ctx.cfg["hn2epub"], instance, feed, db.books_by_period(conn, feed["period"])
        )

    core.generate_opds_index(ctx.cfg["hn2epub"], instance, feeds)


def list_generated_books(ctx):

    import pprint

    conn = db.connect(ctx.cfg["hn2epub"]["db_path"])
    books = db.all_books(conn)
    pp = pprint.PrettyPrinter(indent=2)
    log.info(pp.pformat(books))


def update_best(ctx):
    conn = db.connect(ctx.cfg["hn2epub"]["db_path"])
    day = datetime.utcnow().date()
    with conn:
        hn.update_best_stories(conn, day)


def backfill_best(ctx, start_date, end_date):
    conn = db.connect(ctx.cfg["hn2epub"]["db_path"])
    log.info("Backfilling from %s to %s" % format_range(start_date, end_date))
    with conn:
        hn.backfill_daemonology(conn, start_date, end_date)


def migrate_db(ctx):
    db.migrate(ctx.cfg["hn2epub"]["db_path"])
