import argparse
import logging
import pygit2

from datetime import datetime
from pathlib import Path, PurePath
from typing import Optional

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

    base_path: Optional[Path] = None
    if args.path:
        base_path = args.path if args.path.is_absolute() \
            else args.path.resolve()

    if args.output == OUTPUT_RELATIVE:
        if base_path is None:
            raise CommandError("Cannot render relative paths without a base")

        for repo in repos:
            print(PurePath(repo.workdir).relative_to(base_path))
        return

    if args.output == OUTPUT_URL:
        for repo in repos:
            for remote_name in repo.remotes.names():
                print(repo.remotes[remote_name].url)
        return

    if args.output == OUTPUT_LONG:
        now = datetime.now()

        if base_path is None:
            raise CommandError("Cannot render relative paths without a base")

        for repo in repos:
            f_path = PurePath(repo.workdir).relative_to(base_path)
            f_time = now.strftime("%b %d %H:%M")
            print(f"------ main origin/main {f_time}  {f_path}")

        return

    if args.output != OUTPUT_ABSOLUTE:
        log.warning("unknown output format option '%s'", args.output)

    for repo in repos:
        print(repo.workdir)
