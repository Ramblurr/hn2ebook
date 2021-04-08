import os

from pathlib import Path

import toml

from cerberus import Validator


class InvalidConfigError(Exception):
    """Raise when the application's configuration file is invalid.

    Attributes:
      schema -- the schema the document was validated against
      document -- the config document that failed validation
      errors -- list of the specific validation errors
    """

    def __init__(self, schema, document, errors):
        self.schema = schema
        self.document = document
        self.errors = errors
        self.message = "Invalid configuration"


def read(path):
    return toml.load(path)


def validate(schema, document):
    v = Validator(schema)
    if v.validate(document):
        return True, v.normalized(document)
    return False, v.errors


def load(schema, path):
    if not path:
        raise ValueError("No config file found. Please consult documentation.")
    if not Path(path).is_file:
        raise ValueError(f"Config file {path} cannot be read")
    document = read(path)
    valid, result = validate(schema, document)
    if not valid:
        raise InvalidConfigError(schema, document, result)
    return result


def explain_errors(errors, log):
    log.error("The confguration is invalid:")
    log.error(errors)


def is_dir(field, value, error):
    if not os.path.isdir(value):
        error(field, f"Must be an existing directory ({value})")
