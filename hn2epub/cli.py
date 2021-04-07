import click
import logging
import os
import sys
import importlib.resources

import timestring

from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

from hn2epub.misc import config as configparse
from hn2epub.misc import parse_loglevel

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


def xdg_config_home():
    return os.environ.get("XDG_CONFIG_HOME", str(Path.home().joinpath(".config")))


@click.group(
    help="Generate a standalone epub with best posts (and comments!) from Hacker News"
)
@click.version_option("0.0.1", prog_name="hn2epub")
@click.option(
    "--config",
    envvar="HN2EPUB_CONFIG",
    type=click.Path(file_okay=True, dir_okay=False),
    help="Configuration file",
    show_default=True,
    default=Path(xdg_config_home()).joinpath("hn2epub").joinpath("config.toml"),
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
    help="set the verbosity level",
    show_default=True,
    callback=parse_loglevel,
    default="INFO",
)
@click.option(
    "--logformat",
    envvar="HN2EPUB_LOGFORMAT",
    help="set log format string",
    # default="%(message)s",
)
# @click.option(
#    "--templates",
#    envvar="HN2EPUB_TEMPLATES",
#    help="the folder containing the templates",
#    type=click.Path(file_okay=False, dir_okay=True),
# )
@click.pass_context
def app(ctx, config, logfile, loglevel, logformat):
    global log
    from hn2epub.misc.log import get_logger, setup_logging

    setup_logging(logfile, loglevel, logformat)
    log = get_logger("hn2epub")
    try:
        cfg = configparse.load(config_schema, config)
    except configparse.InvalidConfigError as e:
        configparse.explain_errors(e.errors, log)
        sys.exit(99)

    db_path = str(Path(cfg["hn2epub"]["data_dir"]).joinpath("hn2epub.db"))

    @dataclass
    class Context:
        cfg: dict
        db_path: str

    ctx.obj = Context(cfg, db_path)


@app.command(help="Generate epub from a list of post ids")
@click.pass_obj
@click.option("post_ids", "--post-id", multiple=True, help="An HN post id")
@click.option(
    "--output",
    type=click.Path(file_okay=True, dir_okay=False),
    help="The path to write the epub file to, if not provided the epub will be stored in the data dir. When provided, implies --no-persist",
)
@click.option(
    "--pub-date", default=datetime.utcnow().isoformat(), help="The publication date"
)
def epub_from_posts(ctx, post_ids, output, pub_date):
    from hn2epub import commands

    commands.epub_from_posts(ctx, post_ids, output, pub_date)


@app.command(help="Generate epub for the best posts in a given range")
@click.pass_obj
@click.option(
    "--output",
    type=click.Path(file_okay=True, dir_okay=False),
    help="The path to write the epub file to, if not provided the epub will be stored in the data dir",
)
@click.option("--when", required=True, default="last week", help="The range of time")
@click.option(
    "--limit",
    help="Only the top n posts will be returned, where n is the limit",
    type=int,
    default=100,
)
@click.option(
    "criteria",
    "--sort-criteria",
    help="S",
    type=click.Choice(["time", "time-reverse", "points", "total-comments"]),
    default="points",
)
@click.option(
    "--persist/--no-persist",
    default=True,
    help="If true will persist the generated epub in the database",
)
def epub_from_range(ctx, output, when, limit, criteria, persist):
    from hn2epub import commands

    r = timestring.Range(when)
    commands.epub_from_range(
        ctx, [r[0].date, r[1].date], output, limit, criteria, persist
    )


@app.command(help="Generate opds feed")
@click.pass_obj
@click.option("--output", type=click.Path(), help="The path to write the feed to")
def generate_opds(ctx, output):
    from hn2epub import commands

    commands.generate_opds(ctx)


@app.command(help="List entries in database")
@click.pass_obj
def list_entries(ctx):
    from hn2epub import commands

    commands.list_entries(ctx)


@app.command(help="Update the database of best stories")
@click.pass_obj
def update_best(ctx):
    from hn2epub import commands

    commands.update_best(ctx)


@app.command(help="Update the database of best stories")
@click.pass_obj
def backfill_best(ctx):
    from hn2epub import commands

    commands.backfill_best(ctx)


if __name__ == "__main__":
    app()
