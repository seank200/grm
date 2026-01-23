import argparse
import concurrent.futures
import logging
import pygit2

from pathlib import Path

from .config import subparsers
from .find import find_repos_args, filter_parser
from .render import render_repos, render_parser, parse_render_options


log = logging.getLogger(__name__)


ls_parser = subparsers.add_parser("ls", parents=[filter_parser, render_parser])

ls_parser.add_argument("path", nargs="?", type=Path, default=Path.cwd())
ls_parser.add_argument("-a", "--hidden", action="store_true")
ls_parser.set_defaults(depth=1)


def cmd_ls(args: argparse.Namespace):
    repos = find_repos_args(args)
    render_repos(repos, parse_render_options(args))
