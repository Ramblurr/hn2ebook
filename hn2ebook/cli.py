import re
import logging
import os
import sys
import importlib.resources

import click
import timestring

from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

from hn2ebook import __version__
from hn2ebook.misc import config as configparse
from hn2ebook.misc import parse_loglevel, default_log_format, find_config, xdg_data_home

log = None

config_schema = {
    "hn2ebook": {
        "type": "dict",
        "required": True,
        "schema": {
            "readability_bin": {"type": "string", "required": True},
            "srcsetparser_bin": {"type": "string", "required": True},
            "chromedriver_bin": {"type": "string", "required": True},
            "root_url": {"type": "string", "required": True},
            "data_dir": {"type": "string", "required": True, "default": ""},
            "db_path": {"type": "string", "required": True},
            "instance_name": {
                "type": "string",
                "required": True,
                "default": "hn2ebook",
            },
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


def resolve_data_dir(data_dir, is_xdg_config):
    if not data_dir or len(data_dir) == 0:
        if is_xdg_config:
            return xdg_data_home().joinpath("hn2ebook")
        raise ValueError("config data_dir must be defined")
    else:
        data_dir = Path(data_dir).expanduser()
        if data_dir.is_absolute():
            return data_dir
        return Path(os.getcwd()).joinpath(data_dir).resolve()


def ensure_data_dir(data_dir):
    p = Path(data_dir)
    if not p.exists():
        p.mkdir(mode=0o770)
    elif not p.is_dir():
        raise ValueError(f"config data_dir {data_dir} is not a directory")

    issues_path = p.joinpath("issues")
    issues_path.mkdir(mode=0o770, exist_ok=True)


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(
    context_settings=CONTEXT_SETTINGS,
    help="""
    Create self-contained e-books with the best stories and comments from Hacker News, with embedded comments!
    Requires regular polling of the best stories feed (use the update command in a cron job for that).

    It will look for a config.toml file in the current directory, under $XDG_CONFIG_HOME, or /etc/hn2ebook, or under the HN2EBOOK_CONFIG environment variable.

    Please consult full documentation at https://github.com/ramblurr/hn2ebook
    """,
)
@click.version_option(__version__, prog_name="hn2ebook")
@click.option(
    "--config",
    envvar="HN2EBOOK_CONFIG",
    type=click.Path(file_okay=True, dir_okay=False),
    help="Path to the configuration file",
)
@click.option(
    "--logfile",
    envvar="HN2EBOOK_LOGFILE",
    type=click.Path(file_okay=True, dir_okay=False),
    help="Path to the log file, useful for cron jobs",
    show_default=True,
    default=None,
)
@click.option(
    "--loglevel",
    envvar="HN2EBOOK_LOGLEVEL",
    type=click.Choice(
        ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False
    ),
    help="Set the log level (overrides --verbose)",
    callback=parse_loglevel,
)
@click.option(
    "--logformat",
    envvar="HN2EBOOK_LOGFORMAT",
    help="Set log format string, useful for cron jobs",
    default=default_log_format(),
)
@click.option(
    "--cache/--no-cache",
    default=True,
    help="If enabled, requests to the HN API and daemonology are cached. The cache is stored in a separate sqlite database, next to the primary one. It is name hn2ebook-cache.sqlite.",
)
@click.option("-v", "--verbose", count=True)
@click.pass_context
def app(ctx, config, logfile, loglevel, logformat, cache, verbose):
    global log
    from hn2ebook.misc.log import get_logger, setup_logging

    if not loglevel:
        if verbose == 0:
            loglevel = "INFO"
        elif verbose >= 1:
            loglevel = "DEBUG"
    else:
        loglevel = "INFO"

    setup_logging(logfile, loglevel, logformat)
    log = get_logger("hn2ebook")

    is_xdg_config = False
    if not config:
        config, is_xdg_config = find_config()
    try:
        cfg = configparse.load(config_schema, config)
    except configparse.InvalidConfigError as e:
        configparse.explain_errors(e.errors, log)
        sys.exit(99)

    cfg["hn2ebook"]["data_dir"] = resolve_data_dir(
        cfg["hn2ebook"]["data_dir"], is_xdg_config
    )
    ensure_data_dir(cfg["hn2ebook"]["data_dir"])
    log.debug("resolved data_dir %s" % cfg["hn2ebook"]["data_dir"])

    @dataclass
    class Context:
        cfg: dict

    ctx.obj = Context(cfg)

    if cache:
        from hn2ebook.commands import enable_cache

        enable_cache(ctx.obj)


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
    from hn2ebook import commands

    commands.new_custom_issue(ctx, story_ids, output, criteria)


def validate_range(ctx, param, custom_range):
    if not custom_range:
        return None
    try:
        r = timestring.Range(custom_range)
        date_range = [r[0].date, r[1].date]
        return date_range
    except timestring.TimestringInvalid:
        raise click.BadParameter(
            "range needs to be a simple phrase like 'last 2 weeks' or a YYYY-MM-DD-YYYY-MM-DD string"
        )


@app.command(
    help="""
Create an ebook of the best HN stories for the given period.

There are two ways to select the range in which the best stories are selected

  1) --period and --as-of : supply these two flags to select a logical period as of a certain date

  2) --custom-range : a human string like 'last 2 days' or an absolute range [start,end) in the format YYYY-MM-DD
"""
)
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
    show_default=True,
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
    "--custom-range",
    required=False,
    callback=validate_range,
    help="A range of time, for example 'last week' or YYYY-MM-DD-YYYY-MM-DD, overrides --period and --as-of.",
)
@click.option(
    "--limit",
    help="Only the top n stories will be returned, where n is the limit",
    type=int,
    show_default=True,
    default=10,
)
@click.option(
    "criteria",
    "--sort-criteria",
    help="The sorting criteria",
    type=click.Choice(["time", "time-reverse", "points", "total-comments"]),
    show_default=True,
    default="points",
)
@click.option(
    "--persist/--no-persist",
    default=True,
    help="If true will persist the generated epub in the database",
)
def new_issue(ctx, output, period, as_of, custom_range, limit, criteria, persist):
    from hn2ebook import commands

    if output:
        persist = False

    if custom_range:
        commands.new_issue(ctx, custom_range, None, output, limit, criteria, persist)
    else:
        commands.new_issue(ctx, period, as_of, output, limit, criteria, persist)


@app.command(
    help="Generate an OPDS feed into data_dir. The OPDS feed can be used with e-readers to browse and download the periodicals."
)
@click.pass_obj
@click.option("--output", type=click.Path(), help="The path to write the feed to")
def generate_feed(ctx, output):
    from hn2ebook import commands

    commands.generate_opds(ctx)


@app.command(help="List previously generated issues in database")
@click.pass_obj
def list(ctx):
    from hn2ebook import commands

    commands.list_generated_issues(ctx)


@app.command(
    help="Updates the database of current best stories. Fetches the data from the HN Firebase API's beststories feed. You should run this in a cron job on at least a daily basis."
)
@click.pass_obj
def update(ctx):
    from hn2ebook import commands

    commands.update_best(ctx)


@app.command(
    help="Backfills the database of best stories. Fetches data from cperciva's daily feed at daemonology https://www.daemonology.net/hn-daily/"
)
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
    from hn2ebook import commands

    commands.backfill_best(ctx, start_date, end_date)


@app.command(
    help="Apply all database migrations. Use this after an upgrade, or if the app complains."
)
@click.pass_obj
def migrate_db(ctx):
    from hn2ebook import commands

    commands.migrate_db(ctx)


@app.command(help="Run a static http server to serve the OPML feed and ebook files")
@click.option(
    "--port",
    type=int,
    required=True,
    default=3000,
    help="The port to serve the files on",
)
@click.option(
    "--host",
    type=str,
    required=True,
    default="127.0.0.1",
    help="The hostname to listen on",
)
@click.pass_obj
def server(ctx, host, port):
    from hn2ebook import commands

    commands.server(ctx, host, port)


if __name__ == "__main__":
    app()
