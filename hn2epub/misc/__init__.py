import logging
import click


def parse_loglevel(ctx, param, value):
    x = getattr(logging, value.upper(), None)
    if x is None:
        raise click.BadParameter(
            "Must be CRITICAL, ERROR, WARNING, INFO or DEBUG, not {}"
        )
    return x
