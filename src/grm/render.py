import argparse
import concurrent.futures
import logging
import pygit2

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from pygit2.enums import FileStatus
from rich import print as rich_print
from rich.table import Table
from typing import Optional

from .exceptions import CommandError
from .options import (
    OUTPUT_ABSOLUTE,
    OUTPUT_RELATIVE,
    OUTPUT_URL,
    OUTPUT_LONG,
)
from .utils import max_threads


INDEX_ANY = FileStatus.INDEX_NEW \
    | FileStatus.INDEX_MODIFIED \
    | FileStatus.INDEX_DELETED \
    | FileStatus.INDEX_RENAMED \
    | FileStatus.INDEX_TYPECHANGE

WT_ANY = FileStatus.WT_NEW \
    | FileStatus.WT_MODIFIED \
    | FileStatus.WT_DELETED \
    | FileStatus.WT_RENAMED \
    | FileStatus.WT_TYPECHANGE

log = logging.getLogger(__name__)
now = datetime.now()


@dataclass
class RenderedStatus:
    i: str = "-"
    """index"""

    w: str = "-"
    """worktree"""

    u: str = "-"
    """untracked"""

    a: str = "-"
    """ahead"""

    b: str = "-"
    """behind"""

    c: str = "-"
    """conflicted"""

    d: str = "-"
    """detached"""

    def is_detached(self) -> bool:
        return self.d == "d"

    def render(self) -> str:
        """
        Render a concise representation of repository status

        - (i/-): index
        - (w/-): worktree
        - (u/-): untracked
        - (a/-): ahead
        - (b/-): behind
        - (c/-): conflicted
        - (d/-): detached

        Returns:
            Repository status ("iwuabcd")
        """
        return f"{self.i}{self.w}{self.u}{self.a}{self.b}{self.c}{self.d}"


@dataclass
class RenderedRepo:
    status: RenderedStatus = field(default_factory=RenderedStatus)
    head: str = "-"
    upstream: str = "-"
    time: str = "-"
    path: str = "-"

    def get_row(self) -> tuple[str, ...]:
        return (self.status.render(), self.head, self.upstream, self.time,
                self.path)


def render_sequencer(repo: pygit2.Repository) -> str:
    if repo is None:
        raise ValueError("repo cannot be None")

    git_path = Path(repo.path)

    sequencer = ""
    if (git_path / "rebase-merge").is_dir() \
            or (git_path / "rebase-apply").is_dir():
        sequencer = "rebase"
    elif (git_path / "MERGE_HEAD").is_file():
        sequencer = "merge"
    elif (git_path / "CHERRY_PICK_HEAD").is_file():
        sequencer = "cherry-pick"
    elif (git_path / "REVERT_HEAD").is_file():
        sequencer = "revert"
    elif (git_path / "BISECT_LOG").is_file():
        sequencer = "bisect"
    elif (git_path / "sequencer").is_dir():
        sequencer = "sequencer"  # other sequencer operation

    return sequencer


def render_status(
    repo: pygit2.Repository,
    head: pygit2.Reference,
    head_obj: pygit2.Object
):
    """
    Render the status of the current working tree. This method calls
    `pygit2.Repository.status`, which takes a long time to complete.

    Args:
        repo: Repository to render
        head: A reference to the repository HEAD
        head_obj: The object targeted by HEAD

    Returns:
        A `RenderedRepo` instance
    """

    rendered = RenderedRepo()

    if repo.head_is_unborn:
        # no commits yet
        return rendered

    for flags in repo.status(untracked_files="normal").values():
        if bool(flags & FileStatus.CONFLICTED):
            rendered.status.c = "c"
            break
        elif bool(flags & INDEX_ANY):
            rendered.status.i = "i"
        elif bool(flags & FileStatus.WT_NEW):
            rendered.status.u = "u"
        elif bool(flags & WT_ANY):
            rendered.status.w = "w"

    if repo.head_is_detached:
        rendered.head = str(head_obj.id)[:8]
        rendered.status.d = "d"
    else:
        branch = repo.branches.get(head.shorthand)
        if branch:
            rendered.head = branch.branch_name
            upstream = branch.upstream

            if upstream:
                rendered.upstream = upstream.branch_name
                upstream_oid = repo.references[branch.upstream_name].target

                a, b = repo.ahead_behind(head_obj.id, upstream_oid)
                if a > 0:
                    rendered.status.a = "a"
                if b > 0:
                    rendered.status.b = "b"

    return rendered


def render_timestamp(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp)
    if abs(now - dt) > timedelta(days=180):
        return dt.strftime("%b %d  %Y")
    return dt.strftime("%b %d %H:%M")


def render_path(repo: pygit2.Repository, base_path: Optional[Path]) -> str:
    workdir = PurePath(repo.workdir)
    if base_path and workdir.is_relative_to(base_path):
        return str(workdir.relative_to(base_path))
    return str(workdir)


def render_repo_long(
    repo: pygit2.Repository,
    base_path: Optional[Path] = None,
) -> RenderedRepo:
    if repo is None:
        raise ValueError("repo cannot be None")

    try:
        head = repo.head
    except pygit2.GitError as e:
        log.warning("render: %s: error: %s", repo.workdir, e)
        return RenderedRepo(path=render_path(repo, base_path))

    head_obj = repo.get(head.target)

    rendered = render_status(repo, head, head_obj)  # slow

    if isinstance(head_obj, pygit2.Tag):
        head_obj = head_obj.get_object()

    if isinstance(head_obj, pygit2.Commit):
        rendered.time = render_timestamp(head_obj.commit_time)

    rendered.path = render_path(repo, base_path)

    return rendered


def render_repos_long(
    repos: list[pygit2.Repository],
    base_path: Optional[Path] = None,
):
    num_workers = max_threads(len(repos))
    with ThreadPoolExecutor(max_workers=num_workers) as exec:
        log.info("render: Checking working tree status... (%d threads)",
                 num_workers)

        fs = (exec.submit(render_repo_long, repo, base_path) for repo in repos)

        try:
            waited_fs = concurrent.futures.wait(fs, timeout=300.0)
        except KeyboardInterrupt:
            log.warning("render: aborting")
            for f in fs:
                f.cancel()
            raise

        if log.isEnabledFor(logging.DEBUG):
            cache_used, cache_size = \
                pygit2.option(pygit2.GIT_OPT_GET_CACHED_MEMORY)
            cache_used /= 1024
            cache_size /= 1024
            usage = cache_used / cache_size * 100
            log.debug("render: cached memory: %.2f KB/%.2f KB (%.2f %%)",
                      cache_used, cache_size, usage)

        results = [f.result() for f in waited_fs.done]

    results.sort(key=lambda r: r.path)

    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column("Status")
    table.add_column("HEAD")
    table.add_column("Upstream")
    table.add_column("Commit Time")
    table.add_column("Path")

    for result in results:
        table.add_row(*result.get_row())

    rich_print(table)


def render_repos(
    repos: list[pygit2.Repository],
    args: argparse.Namespace,
):
    """Render repositories"""
    if not repos:
        return

    base_path: Optional[Path] = None
    if args.path:
        base_path = args.path if args.path.is_absolute() \
            else args.path.resolve()

    if args.output == OUTPUT_LONG:
        render_repos_long(repos, base_path)
        log.debug("i: index, w: working tree, u: untracked, a: ahead, "
                  "b: behind, c: conflict, d: detached HEAD")
        return

    repos.sort(key=lambda repo: repo.workdir)

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

    if args.output != OUTPUT_ABSOLUTE:
        log.warning("unknown output format option '%s'", args.output)

    for repo in repos:
        print(repo.workdir)
