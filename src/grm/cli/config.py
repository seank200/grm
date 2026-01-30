import argparse
import logging
import sys

from pathlib import Path


log = logging.getLogger(__name__)

parser = argparse.ArgumentParser(prog="grm", description="Git Repository Manager")

logging_group = parser.add_mutually_exclusive_group()
logging_group.add_argument(
    "--debug",
    action="store_const",
    const=logging.DEBUG,
    dest="logging_level",
    help=argparse.SUPPRESS,
)
logging_group.add_argument(
    "-q",
    "--quiet",
    action="store_const",
    const=logging.ERROR,
    dest="logging_level",
    help="Suppress informational logs",
)
logging_group.add_argument(
    "-v",
    "--verbose",
    action="store_const",
    const=logging.INFO,
    dest="logging_level",
    help="Show more detailed logs",
)
logging_group.set_defaults(logging_level=logging.WARNING)

subparsers = parser.add_subparsers(title="subcommands")


def configure(args):
    if args.logging_level <= logging.DEBUG:
        fmt = "%(name)s [%(threadName).24s] -- [%(levelname)s] %(message)s"
    elif args.logging_level <= logging.INFO:
        fmt = "%(name)s: %(message)s"
    else:
        fmt = "%(message)s"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))

    logger = logging.getLogger(__name__.split(".", 1)[0])
    logger.addHandler(handler)
    logger.setLevel(args.logging_level)

    if hasattr(args, "path") and isinstance(args.path, Path):
        args.path = args.path.expanduser().resolve()

    if log.isEnabledFor(logging.DEBUG):
        log.debug("args: %s", sys.argv)
        log.debug("parsed args: %s", vars(args))
