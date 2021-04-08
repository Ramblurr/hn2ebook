import click
import logging
import os
import sys
import importlib.resources

import timestring

from datetime import datetime, timedelta
from dataclasses import dataclass

from hn2epub.misc import config as configparse
from hn2epub.misc import parse_loglevel, default_log_format, find_config

log = None

config_schema = {
    "hn2epub": {
        "type": "dict",
        "required": True,
        "schema": {
            "readability_bin": {"type": "string", "required": True},
            "srcsetparser_bin": {"type": "string", "required": True},
            "chromedriver_bin": {"type": "string", "required": True},
            "root_url": {"type": "string", "required": True},
            "data_dir": {"type": "string", "required": True},
            "db_path": {"type": "string", "required": True},
            "instance_name": {"type": "string", "required": True, "default": "hn2epub"},
            "n_concurrent_requests": {
                "type": "integer",
                "required": True,
                "default": 5,
            },
            "use_chrome": {"type": "boolean", "required": False, "default": True},
        },
    },
    "pushover": {
        "type": "dict",
        "required": False,
        "schema": {
            "enabled": {"type": "boolean", "required": False, "default": False},
            "token": {"type": "string", "required": False},
            "user": {"type": "string", "required": False},
        },
    },
}


@click.group(
    help="Generate a standalone epub with best stories (and comments!) from Hacker News"
)
@click.version_option("0.0.1", prog_name="hn2epub")
@click.option(
    "--config",
    envvar="HN2EPUB_CONFIG",
    type=click.Path(file_okay=True, dir_okay=False),
    help="Configuration file",
)
@click.option(
    "--logfile",
    envvar="HN2EPUB_LOGFILE",
    type=click.Path(file_okay=True, dir_okay=False),
    help="Log file",
    show_default=True,
    default=None,
)
@click.option(
    "--loglevel",
    envvar="HN2EPUB_LOGLEVEL",
    type=click.Choice(
        ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False
    ),
    help="Set the log level (overrides --verbose)",
    callback=parse_loglevel,
)
@click.option("-v", "--verbose", count=True)
@click.option(
    "--logformat",
    envvar="HN2EPUB_LOGFORMAT",
    help="set log format string",
    default=default_log_format(),
)
@click.pass_context
def app(ctx, config, logfile, loglevel, verbose, logformat):
    global log
    from hn2epub.misc.log import get_logger, setup_logging

    if not loglevel:
        if verbose == 0:
            loglevel = "INFO"
        elif verbose >= 1:
            loglevel = "DEBUG"
    else:
        loglevel = "INFO"

    setup_logging(logfile, loglevel, logformat)
    log = get_logger("hn2epub")

    if not config:
        config = find_config()
    try:
        cfg = configparse.load(config_schema, config)
    except configparse.InvalidConfigError as e:
        configparse.explain_errors(e.errors, log)
        sys.exit(99)

    @dataclass
    class Context:
        cfg: dict

    ctx.obj = Context(cfg)


@app.command(help="Create epub from a hand-picked list of story ids")
@click.pass_obj
@click.option("story_ids", "--story-id", multiple=True, help="An HN story id")
@click.option(
    "--output",
    required=True,
    type=click.Path(file_okay=True, dir_okay=False),
    help="The path to write the epub file to, if not provided the epub will be stored in the data dir. When provided, implies --no-persist",
)
@click.option(
    "criteria",
    "--sort-criteria",
    help="The sorting criteria",
    required=True,
    type=click.Choice(["time", "time-reverse", "points", "total-comments"]),
    default="points",
)
def custom_issue(ctx, story_ids, output, criteria):
    from hn2epub import commands

    commands.new_custom_issue(ctx, story_ids, output, criteria)


@app.command(help="Create epub of the best HN stories in a period")
@click.pass_obj
@click.option(
    "--output",
    type=click.Path(file_okay=True, dir_okay=False),
    help="The path to write the epub file to, if not provided the epub will be stored in the data dir",
)
@click.option(
    "--period",
    required=True,
    default="weekly",
    type=click.Choice(["daily", "weekly", "monthly"]),
    help="The period type",
)
@click.option(
    "--as-of",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=datetime.now().strftime("%Y-%m-%d"),
    help="The last day of the period",
)
@click.option(
    "--custom-range", required=False, help="A range of time, for example 'last week'"
)
@click.option(
    "--limit",
    help="Only the top n stories will be returned, where n is the limit",
    type=int,
    default=10,
)
@click.option(
    "criteria",
    "--sort-criteria",
    help="The sorting criteria",
    type=click.Choice(["time", "time-reverse", "points", "total-comments"]),
    default="points",
)
@click.option(
    "--persist/--no-persist",
    default=True,
    help="If true will persist the generated epub in the database",
)
def new_issue(ctx, output, period, as_of, custom_range, limit, criteria, persist):
    from hn2epub import commands

    if output:
        persist = False

    if custom_range:
        r = timestring.Range(custom_range)
        date_range = [r[0].date, r[1].date]
        commands.new_issue(ctx, date_range, None, output, limit, criteria, persist)
    else:
        commands.new_issue(ctx, period, as_of, output, limit, criteria, persist)


@app.command(help="Generate an OPDS feed")
@click.pass_obj
@click.option("--output", type=click.Path(), help="The path to write the feed to")
def generate_feed(ctx, output):
    from hn2epub import commands

    commands.generate_opds(ctx)


@app.command(help="List previously generated issues in database")
@click.pass_obj
def list(ctx):
    from hn2epub import commands

    commands.list_generated_books(ctx)


@app.command(help="Update the database of best stories")
@click.pass_obj
def update(ctx):
    from hn2epub import commands

    commands.update_best(ctx)


@app.command(help="Update the database of best stories from cperciva's feed")
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    default=(datetime.today() - timedelta(days=7)).date().strftime("%Y-%m-%d"),
    help="The start date to backfill from, 2021-01-01",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    default=datetime.today().date().strftime("%Y-%m-%d"),
    help="The end date to backfill to (but not including), 2021-02-01",
)
@click.pass_obj
def backfill(ctx, start_date, end_date):
    from hn2epub import commands

    commands.backfill_best(ctx, start_date, end_date)


@app.command(help="Migrate the database")
@click.pass_obj
def migrate_db(ctx):
    from hn2epub import commands

    commands.migrate_db(ctx)


if __name__ == "__main__":
    app()
