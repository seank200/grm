import concurrent.futures
import enum
import logging
import os
import pygit2

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from pygit2.enums import FileStatus
from typing import Optional, Type

from .config import config, relative_workdir
from .remote import RemoteUrl


NOW = datetime.now()

log = logging.getLogger(__name__)


class RenderFormat(enum.StrEnum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    LONG = "long"


@dataclass
class RenderResult:
    path: str
    index: bool = False
    worktree: bool = False
    untracked: bool = False
    ahead: bool = False
    behind: bool = False
    conflicted: bool = False
    detached: bool = False

    head: str = ""
    remote: str = ""
    last_modified: Optional[datetime] = None

    def render_status(self) -> str:
        s = ""
        s += "i" if self.index else "-"
        s += "w" if self.worktree else "-"
        s += "u" if self.untracked else "-"
        s += "a" if self.ahead else "-"
        s += "b" if self.behind else "-"
        s += "c" if self.conflicted else "-"
        s += "d" if self.detached else "-"
        return s

    def render_head(self) -> str:
        return self.head if self.head else "-"

    def render_remote(self) -> str:
        return self.remote if self.remote else "-"

    def render_last_modified(self) -> str:
        if self.last_modified is None:
            return "--- -- --:--"

        if abs(self.last_modified - NOW) > timedelta(days=180):
            fmt = "%b %d, %Y"  # Jan 01, 2025
        else:
            fmt = "%b %d %H:%M"  # Jan 01 18:43

        return self.last_modified.strftime(fmt)

    def render_path(self) -> str:
        if config.base_path is not None:
            path = Path(self.path)
            if path.is_relative_to(config.base_path):
                return str(path.relative_to(config.base_path))
        return self.path


class RenderResults:
    MAX_WIDTH = 24

    def __init__(self, results: Sequence[RenderResult]):
        self.results = results
        self.width_head = 0
        self.width_remote = 0

        self.iter = 0

    def analyze(self):
        width_head = 0
        width_remote = 0

        for result in self.results:
            width_head = max(len(result.render_head()), width_head)
            width_remote = max(len(result.render_remote()), width_remote)

        self.width_head = width_head
        self.width_remote = width_remote

    def __iter__(self):
        self.iter = 0
        self.analyze()
        return self

    def __next__(self) -> str:
        if self.iter >= len(self.results):
            raise StopIteration

        result = self.results[self.iter]
        self.iter += 1

        head = result.render_head()
        if len(head) > self.width_head:
            head = head[: self.width_head - 2] + ".."
        remote = result.render_remote()
        if len(remote) > self.width_remote:
            remote = remote[: self.width_remote - 2] + ".."

        return (
            result.render_status()
            + " "
            + ("{:<" + str(self.width_head) + "}").format(head)
            + " "
            + ("{:<" + str(self.width_remote) + "}").format(remote)
            + " "
            + result.render_last_modified()
            + " "
            + result.render_path()
        )


INDEX_ANY = (
    FileStatus.INDEX_NEW
    | FileStatus.INDEX_MODIFIED
    | FileStatus.INDEX_DELETED
    | FileStatus.INDEX_RENAMED
    | FileStatus.INDEX_TYPECHANGE
)

WT_ANY = (
    FileStatus.WT_NEW
    | FileStatus.WT_MODIFIED
    | FileStatus.WT_DELETED
    | FileStatus.WT_RENAMED
    | FileStatus.WT_TYPECHANGE
)


def _worker_render(path: str) -> RenderResult:
    repo = pygit2.Repository(path)
    result = RenderResult(path)

    if repo.head_is_unborn:
        result.head = repo.head.shorthand
        return result

    head_obj = repo.get(repo.head.target)
    if isinstance(head_obj, pygit2.Commit):
        result.last_modified = datetime.fromtimestamp(head_obj.commit_time)

    if repo.head_is_detached:
        result.head = str(repo.head.target)[:8]
        result.detached = True
        return result

    head = repo.branches.get(repo.head.shorthand)
    if head is None:
        return result

    result.head = head.branch_name

    upstream = head.upstream
    if upstream is not None:
        a, b = repo.ahead_behind(head.target, upstream.target)
        result.ahead = a > 0
        result.behind = b > 0

        try:
            remote = repo.remotes[upstream.remote_name]
            if remote.url:
                result.remote = RemoteUrl.parse(remote.url).owner()
        except KeyError:
            pass

    for stat in repo.status(untracked_files="normal").values():
        if stat & FileStatus.CONFLICTED:
            result.conflicted = True
            break
        elif stat & FileStatus.WT_NEW:
            result.untracked = True
        elif stat & WT_ANY:
            result.worktree = True
        elif stat & INDEX_ANY:
            result.index = True

    return result


def _executor() -> concurrent.futures.Executor:
    """
    Determine the best Executor type to use in rendering, depending on
    the number of CPU cores in the machine
    """
    cpu_count = os.cpu_count() or 1
    if cpu_count == 1:  # single-core environment
        Executor: Type[concurrent.futures.Executor] = (
            concurrent.futures.ThreadPoolExecutor
        )
        num_workers = 2
        log.debug("render: Rendering with %d threads", num_workers)
    else:
        Executor: Type[concurrent.futures.Executor] = (
            concurrent.futures.ProcessPoolExecutor
        )
        num_workers = cpu_count // 2 if cpu_count > 8 else cpu_count
        log.debug("render: Rendering with %d processes", num_workers)

    return Executor(max_workers=num_workers)


def render_repos(
    repos: list[pygit2.Repository], fmt: RenderFormat = RenderFormat.RELATIVE
):
    if fmt == RenderFormat.RELATIVE:
        for repo in repos:
            print(relative_workdir(repo))
        return

    if fmt == RenderFormat.ABSOLUTE:
        for repo in repos:
            print(repo.workdir)
        return

    with _executor() as executor:
        fs = tuple(executor.submit(_worker_render, repo.workdir) for repo in repos)
        try:
            waited_fs = concurrent.futures.wait(fs, timeout=10.0)
        except KeyboardInterrupt:
            log.warning("render: Aborting")
            for f in fs:
                f.cancel()
            raise

        results = list(f.result() for f in waited_fs.done)

    log.debug("render: Sorting results")
    results.sort(key=lambda r: r.path)

    for line in RenderResults(results):
        print(line)
