import argparse

from pathlib import Path

from .find import find_repos
from .options import subparsers, render_parser, EPILOG_LONG
from .render import render_repos


parser = subparsers.add_parser(
    "ls",
    description="List repositories in a directory",
    epilog=EPILOG_LONG,
    parents=[render_parser],
    help="List repositories in a directory",
)

parser.add_argument(
    "path",
    nargs='?',
    default=Path.cwd(),
    type=Path,
    help="directory path to search",
)

parser.add_argument(
    "-a",
    action="store_const",
    const=True,
    help="alias for '--hidden'",
    dest="hidden",
)


def cmd_ls(args: argparse.Namespace):
    repos = find_repos(args.path, max_depth=1)
    render_repos(repos, args)
