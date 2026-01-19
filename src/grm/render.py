import argparse
import logging
import pygit2

from datetime import datetime
from pathlib import Path, PurePath
from pygit2.enums import FileStatus
from typing import Optional

from .exceptions import CommandError
from .options import (
    OUTPUT_ABSOLUTE,
    OUTPUT_RELATIVE,
    OUTPUT_URL,
    OUTPUT_LONG,
)


log = logging.getLogger(__name__)


def render_status(repo: pygit2.Repository) -> str:
    """
    Render a concise representation of repository status

    "iwuabo"
    i: index, w: worktree, u: untracked
    a: ahead, b: behind
    o: (operation in progress)
        m: merge, r: rebase, c: cherry-pick, v: revert, b: bisect

    Args:
        repo: Repository

    Returns:
        Repository status

    Raises:
        ValueError if repo is None
    """
    if repo is None:
        raise ValueError("repo cannot be None")

    git_path = Path(repo.path)

    operation = "-"
    if (git_path / "rebase-merge").is_dir() \
            or (git_path / "rebase-apply").is_dir():
        operation = "r"  # rebase
    elif (git_path / "MERGE_HEAD").is_file():
        operation = "m"  # merge
    elif (git_path / "CHERRY_PICK_HEAD").is_file():
        operation = "c"  # cherry-pick
    elif (git_path / "REVERT_HEAD").is_file():
        operation = "v"  # verbose
    elif (git_path / "BISECT_LOG").is_file():
        operation = "b"  # bisect
    elif (git_path / "sequencer").is_dir():
        operation = "o"  # other sequencer operation

    status = repo.status(untracked_files="normal")

    for flags in status.values():
        pass

    return f"-----{operation}"


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
