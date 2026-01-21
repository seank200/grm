import argparse
import concurrent.futures
import logging
import pygit2

from pathlib import Path

from .config import subparsers
from .find import find_repos_args, filter_parser
from .render import render_repos, RenderFormat


log = logging.getLogger(__name__)


ls_parser = subparsers.add_parser("ls", parents=[filter_parser])

ls_parser.add_argument("path", nargs="?", type=Path, default=Path.cwd())
ls_parser.add_argument("-l", action="store_true", dest="long")
ls_parser.add_argument("-a", "--hidden", action="store_true")
ls_parser.set_defaults(depth=1)


def _worker(repo):
    repo.status()


def status_repos(repos: list[pygit2.Repository]):
    with concurrent.futures.ProcessPoolExecutor() as executor:
        fs = (executor.submit(_worker, repo) for repo in repos)
        concurrent.futures.wait(fs, timeout=10.0)


def cmd_ls(args: argparse.Namespace):
    repos = find_repos_args(args)

    render_repos(repos, RenderFormat.LONG if args.long else RenderFormat.RELATIVE)
