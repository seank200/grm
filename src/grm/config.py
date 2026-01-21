import argparse
import logging
import os
import sys
import pygit2

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Type

from .exceptions import ArgValueError


LEVELS = (
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL,
)


@dataclass
class Config:
    base_path: Path = field(default_factory=Path.home)
    log_level: int = logging.INFO
    debug: bool = False


config = Config()

log = logging.getLogger(__name__)

parser = argparse.ArgumentParser(
    prog="grm",
    description="Git repository manager",
)

parser.set_defaults(cmd=None)

logging_group = parser.add_mutually_exclusive_group()

logging_group.add_argument(
    "-q",
    "--quiet",
    action="count",
    default=0,
    help="Suppress informational logs",
)

logging_group.add_argument(
    "-v",
    "--verbose",
    action="store_true",
)

logging_group.add_argument(
    "--debug",
    action="store_true",
    help=argparse.SUPPRESS,
)

subparsers = parser.add_subparsers()

config_parser = subparsers.add_parser("config")


def envvar(key: str, value_type: Type = str):
    value = os.environ.get(key)

    if value_type is bool:
        return value.lower() in ("1", "true") if value else False

    if value is None:
        return None

    if value_type is int:
        try:
            return int(value)
        except ValueError:
            raise ArgValueError("Not a valid integer", envvar=key)

    if value_type is float:
        try:
            return float(value)
        except ValueError:
            raise ArgValueError("Not a valid integer", envvar=key)

    if value_type is Path:
        try:
            return Path(value)
        except TypeError:
            raise ArgValueError("Not a valid path", envvar=key)

    return value_type


def relative_workdir(
    repo: pygit2.Repository,
) -> Path:
    path = Path(repo.workdir)
    if path.is_relative_to(config.base_path):
        return path.relative_to(config.base_path)
    return path


def configure(args):
    fmt = "%(message)s"

    debug = args.debug or envvar("GRM_DEBUG", bool)
    quiet = args.quiet or envvar("GRM_QUIET", int)
    verbose = args.verbose or envvar("GRM_VERBOSE", int)

    if debug:
        config.debug = True
        config.log_level = logging.DEBUG
        fmt = "%(levelname)s [%(name)s]  %(message)s"
    elif quiet:
        config.log_level = LEVELS[min(args.quiet, len(LEVELS))]
    elif verbose:
        config.log_level = logging.DEBUG

    if hasattr(args, "path") and isinstance(args.path, Path):
        config.base_path = args.path.expanduser().resolve()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt))

    logger = logging.getLogger(__name__.split(".", 1)[0])  # Package config
    logger.addHandler(handler)
    logger.setLevel(config.log_level)

    if config.debug:
        log.debug("command args: %s", vars(args))


def cmd_config(args):
    for k, v in asdict(config).items():
        print(k, v, sep="\t")
