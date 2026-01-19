import argparse
import logging
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Type
from .exceptions import ConfigError
from .options import subparsers


@dataclass
class Config:
    verbose: bool = False
    quiet: bool = False
    debug: bool = False
    no_env: bool = False
    """Ignore OS environment variables"""


config = Config()

log = logging.getLogger(__name__)

parser = subparsers.add_parser("config", help="Show program config")

ENV_TYPE_ERROR = """Expected environment variable '{}' to be of type '{}',
but instead got value '{}'."""


def envvar(key: str, value_type: Type[str | int | float | bool | Path] = str):
    if config.no_env:
        return None

    value = os.environ.get(key)

    if value is None:
        return False if value_type is bool else None

    if value_type is bool:
        return value.lower() in ("1", "true")

    if value_type is int:
        try:
            return int(value)
        except ValueError:
            raise ConfigError(ENV_TYPE_ERROR.format(key, 'int', value))

    if value_type is Path:
        try:
            return Path(value_type)
        except TypeError:
            raise ConfigError(ENV_TYPE_ERROR.format(key, 'Path', value))

    if value_type is float:
        try:
            return float(value)
        except ValueError:
            raise ConfigError(ENV_TYPE_ERROR.format(key, 'float', value))

    # value_type is str. return as-is.
    return value


def configure(args: argparse.Namespace):
    if args.no_env:
        config.no_env = True

    if args.quiet:
        config.quiet = True
    elif envvar("GRM_QUIET", bool):
        config.quiet = True

    if args.verbose:
        config.verbose = True
    elif not config.quiet and envvar("GRM_VERBOSE", bool):
        config.verbose = True

    if args.debug:
        config.debug = True
    elif not config.quiet and envvar("GRM_DEBUG", bool):
        config.debug = True

    if config.quiet:
        level = logging.ERROR
        fmt = "%(levelname)s: %(message)s"
    elif config.debug:
        level = logging.DEBUG
        fmt = "%(asctime)s  %(levelname)s [%(name)s] -- %(message)s"
    elif config.verbose:
        level = logging.DEBUG
        fmt = "%(name)s: %(message)s"
    else:
        level = logging.INFO
        fmt = "%(message)s"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt))

    logger = logging.getLogger(__name__.split(".", 1)[0])
    logger.setLevel(level)
    logger.addHandler(handler)

    log.debug("application args: %s", vars(args))


def cmd_config(args: argparse.Namespace):
    for k, v in asdict(config).items():
        print(k, v, sep="\t")

    if args.debug:
        print("---")
        for k, v in vars(args).items():
            print(k, v, sep="\t")
