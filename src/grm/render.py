import argparse
import logging
import pygit2

from datetime import datetime
from pathlib import PurePath

from .exceptions import CommandError
from .options import (
    OUTPUT_ABSOLUTE,
    OUTPUT_RELATIVE,
    OUTPUT_URL,
    OUTPUT_LONG,
)


log = logging.getLogger(__name__)


def render_repos(
    repos: list[pygit2.Repository],
    args: argparse.Namespace,
):
    """Render repositories"""
    if not repos:
        return

    repos.sort(key=lambda repo: repo.workdir)

    if args.output == OUTPUT_RELATIVE:
        if not args.path:
            raise CommandError("Cannot render relative paths without a base")

        for repo in repos:
            print(PurePath(repo.workdir).relative_to(args.path))
        return

    if args.output == OUTPUT_URL:
        for repo in repos:
            for remote_name in repo.remotes.names():
                print(repo.remotes[remote_name].url)
        return

    if args.output == OUTPUT_LONG:
        now = datetime.now()

        if not args.path:
            raise CommandError("Cannot render relative paths without a base")

        for repo in repos:
            f_path = PurePath(repo.workdir).relative_to(args.path)
            f_time = now.strftime("%b %d %H:%M")
            print(f"------ main origin/main {f_time}  {f_path}")

        return

    if args.output != OUTPUT_ABSOLUTE:
        log.warning("unknown output format option '%s'", args.output)

    for repo in repos:
        print(repo.workdir)
