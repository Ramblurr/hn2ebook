import sys
import os
import logging
import click
from pathlib import Path


def parse_loglevel(ctx, param, value):
    if not value:
        return None
    x = getattr(logging, value.upper(), None)
    if x is None:
        raise click.BadParameter(
            "Must be CRITICAL, ERROR, WARNING, INFO or DEBUG, not {}"
        )
    return x


def default_log_format():
    if sys.stdout.isatty():
        return "%(message)s"
    return None


def xdg_config_home():
    return os.environ.get("XDG_CONFIG_HOME", str(Path.home().joinpath(".config")))


def find_config():
    look_order = [
        Path(os.getcwd()),
        Path(xdg_config_home()).joinpath("hn2ebook"),
        Path("/etc/hn2ebook"),
    ]
    for loc in look_order:
        config = loc.joinpath("config.toml")
        if config.is_file():
            return str(config)
    return None
