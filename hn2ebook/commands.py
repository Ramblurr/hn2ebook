import sys

from uuid import uuid4
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta


import click
import requests_cache

from hn2ebook import core
from hn2ebook import hn
from hn2ebook import db
from hn2ebook.misc.log import logger

log = logger.get_logger("commands")

requests_cache.install_cache("hn2ebook")


def isoformat(d):
    return d.isoformat() + "Z"


def persist_epub_meta(conn, at, stories, meta, epub_path_name, period):
    story_ids = [story["id"] for story in stories]

    assert len(story_ids) == meta["num_stories"]

    issue = {
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

    db.insert_issue(conn, issue, story_ids, formats, period)


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
            longtitle = "%s (%s)" % (title, params["as_of"].strftime("%a, %d %b, %Y"))
            subtitle = params["as_of"].strftime("for the day of %a, %d %b, %Y")
        elif period == "weekly":
            longtitle = "%s (%s)" % (title, params["as_of"].strftime("%a, %d %b, %Y"))
            subtitle = params["as_of"].strftime("for week %V of %Y")
        elif period == "monthly":
            longtitle = "%s (%s)" % (title, params["as_of"].strftime("%Y %B"))
            subtitle = params["as_of"].strftime("for the month of %B %Y")
    elif "start" in params:
        start = params["start"]
        end = params["end"]
        title = f"Hacker News Digest"
        start_str, end_str = format_range(start, end)
        longtitle = "%s (%s to %s)" % (title, start_str, end_str)
        subtitle = "for %s to %s" % (start_str, end_str)
    elif "story_ids" in params:
        title = f"Hacker News Series"
        longtitle = title
        subtitle = "the finest %d hand-picked stories" % (len(params["story_ids"]))

    return title, longtitle, subtitle


def epub_headlines(stories):
    headlines = []
    for story in stories:
        title = story["title"]
        headlines.append(title)
    return headlines


def issue_meta(stories, creation_params, pub_date, uuid):
    title, longtitle, subtitle = epub_title(creation_params)
    headlines_list = epub_headlines(stories)
    return {
        "title": title,
        "longtitle": longtitle,
        "subtitle": subtitle,
        "num_stories": len(stories),
        "identifier": "urn:uuid:%s" % uuid,
        "uuid": uuid,
        "authors": ["hn2ebook"],
        "language": "en",
        "headlines": headlines_list,
        "DC": {"subject": "News", "date": pub_date, "publisher": "hn2ebook",},
    }


def check_writable(path):
    try:
        f = open(path, "w")
        f.close()
    except:
        raise click.BadParameter(f"cannot write to output path {path}")


def get_output_path(cfg, user_output, suffix):
    issues_path = Path(cfg["data_dir"]).joinpath("issues")
    if not user_output:
        output = issues_path.joinpath(f"hn2ebook-{suffix}.epub")
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
    cfg = ctx.cfg["hn2ebook"]
    now = datetime.utcnow()

    if isinstance(period_or_range, str) and period_or_range in period_to_delta:
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
        date_range = period_or_range
        log.info(
            "creating periodical with range %s, with limit=%s, sort_criteria=%s"
            % (date_range, limit, criteria)
        )
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
    if len(stories) == 0:
        log.info(
            "No stories were found in the given range. You should run the backfill command."
        )
        sys.exit(2)

    log.info("collected %d stories for the issue" % len(stories))
    meta = issue_meta(stories, creation_params, isoformat(now), str(uuid4()))

    epub_path = core.epub_from_stories(cfg, stories, meta, output)

    if persist:
        with db.connect(cfg["db_path"]) as conn:
            persist_epub_meta(conn, now, stories, meta, epub_path, period)


def new_custom_issue(ctx, story_ids, user_output, criteria):
    cfg = ctx.cfg["hn2ebook"]
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
    cfg = ctx.cfg["hn2ebook"]
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
            "content": "Daily periodicals of the best stories on Hacker News",
        },
        {
            "period": "weekly",
            "name": "Hacker News Weekly",
            "url": f"/weekly.xml",
            "up_url": f"/index.xml",
            "start_url": f"/index.xml",
            "content": "Weekly periodicals of the best stories on Hacker News",
        },
        {
            "period": "monthly",
            "name": "Hacker News Monthly",
            "url": f"/monthly.xml",
            "up_url": f"/index.xml",
            "start_url": f"/index.xml",
            "content": "Monthly periodicals of the best stories on Hacker News",
        },
    ]

    for feed in feeds:
        core.generate_opds(
            ctx.cfg["hn2ebook"],
            instance,
            feed,
            db.issues_by_period(conn, feed["period"]),
        )

    core.generate_opds_index(ctx.cfg["hn2ebook"], instance, feeds)

    log.info("OPDS feed available at %s/index.xml" % ctx.cfg["hn2ebook"]["root_url"])


def list_generated_issues(ctx):

    import pprint

    conn = db.connect(ctx.cfg["hn2ebook"]["db_path"])
    issues = db.all_issues(conn)
    pp = pprint.PrettyPrinter(indent=2)
    log.info(pp.pformat(issues))


def update_best(ctx):
    conn = db.connect(ctx.cfg["hn2ebook"]["db_path"])
    day = datetime.utcnow().date()
    with conn:
        hn.update_best_stories(conn, day)


def backfill_best(ctx, start_date, end_date):
    conn = db.connect(ctx.cfg["hn2ebook"]["db_path"])
    log.info("Backfilling from %s to %s" % format_range(start_date, end_date))
    with conn:
        hn.backfill_daemonology(conn, start_date, end_date)


def migrate_db(ctx):
    db.migrate(ctx.cfg["hn2ebook"]["db_path"])
