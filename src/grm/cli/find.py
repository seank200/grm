import argparse

from datetime import datetime, timedelta
from grm.git import find_repos
from pathlib import Path

from .config import subparsers
from .render import render_repos, parent_parser as render_parent_parser


parent_parser = argparse.ArgumentParser(add_help=False)
parent_parser.add_argument("path", type=Path, help="Search path (a directory)")
parent_parser.add_argument(
    "-d", "--depth", type=int, default=0, help="Search depth [default: 0 (no limit)]"
)
parent_parser.add_argument(
    "-n", "--name", default="", help="Repository workdir basename filter"
)
parent_parser.add_argument(
    "-u", "--url", default="", dest="remote_url", help="Remote repository URL filter"
)

parser = subparsers.add_parser(
    "find",
    parents=[parent_parser, render_parent_parser],
    help="Recursively search for repositories",
)


def cmd_find(args):
    repos = find_repos(
        args.path, args.depth, name=args.name, remote_url=args.remote_url
    )

    render_repos(
        repos,
        relative_to=args.path,
        one=args.output_one,
        long=args.output_long,
        sort=True,
    )
