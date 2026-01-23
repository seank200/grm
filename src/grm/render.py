import argparse
import concurrent.futures
import enum
import logging
import os
import pygit2

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePath
from pygit2.enums import FileStatus
from typing import Type, Literal

from .config import config, relative_dir
from .remote import RemoteUrl


class RenderFormat(enum.StrEnum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    LONG = "long"


class RenderOptions(enum.IntFlag):
    DEFAULT = enum.auto()
    LONG = enum.auto()
    COMMIT_TIME = enum.auto()  # descending sort on commit_time
    REVERSE = enum.auto()  # reverse the sort order


NOW = datetime.now()

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

log = logging.getLogger(__name__)

render_parser = argparse.ArgumentParser(add_help=False)
render_parser.add_argument("-l", action="store_true", dest="long")
render_parser.add_argument("-t", action="store_true", dest="commit_time")
render_parser.add_argument("-r", action="store_true", dest="reverse")


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
    shallow: bool = False

    head: str = ""
    remote: str = ""
    commit_time: int = -1

    def render_status(self) -> str:
        s = ""
        s += "i" if self.index else "-"
        s += "w" if self.worktree else "-"
        s += "u" if self.untracked else "-"
        s += "a" if self.ahead else "-"
        s += "b" if self.behind else "-"
        s += "c" if self.conflicted else "-"
        s += "d" if self.detached else "-"
        s += "s" if self.shallow else "-"
        return s

    def render_head(self) -> str:
        return self.head if self.head else "-"

    def render_remote(self) -> str:
        return self.remote if self.remote else "-"

    def render_commit_time(self) -> str:
        if self.commit_time < 0:
            return "-           "

        commit_time_dt = datetime.fromtimestamp(self.commit_time)
        if abs(NOW - commit_time_dt) > timedelta(days=180):
            fmt = "%b %d, %Y"  # Jan 01, 2025
        else:
            fmt = "%b %d %H:%M"  # Jan 01 18:43

        return commit_time_dt.strftime(fmt)

    def render_path(self) -> str:
        return str(relative_dir(PurePath(self.path)))


class RenderResults:
    MAX_WIDTH = 24

    def __init__(self, results: Sequence[RenderResult], options: RenderOptions):
        self.results = results
        self.options = options

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

        path = result.render_path()
        if not self.options & RenderOptions.LONG:
            return path

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
            + result.render_commit_time()
            + " "
            + result.render_path()
        )


def _worker_render(path: str) -> RenderResult:
    repo = pygit2.Repository(path)
    result = RenderResult(repo.workdir)

    if repo.is_bare or repo.is_empty:
        return result

    if repo.head_is_unborn:
        result.head = "(unborn)"
        return result

    result.shallow = repo.is_shallow

    head_obj = repo.get(repo.head.target)
    if isinstance(head_obj, pygit2.Commit):
        result.commit_time = head_obj.commit_time

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


def parse_render_options(args: argparse.Namespace) -> RenderOptions:
    options = RenderOptions.DEFAULT

    if args.long:
        options |= RenderOptions.LONG
    if args.commit_time:
        options |= RenderOptions.COMMIT_TIME
    if args.reverse:
        options |= RenderOptions.REVERSE

    return options


def render_executor() -> concurrent.futures.Executor:
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
    repos: list[pygit2.Repository], options: RenderOptions = RenderOptions.DEFAULT
):
    if options & RenderOptions.LONG:
        log.debug("render: Reading repository index")
        with render_executor() as executor:
            fs = tuple(executor.submit(_worker_render, repo.workdir) for repo in repos)
            try:
                waited_fs = concurrent.futures.wait(fs, timeout=10.0)
            except KeyboardInterrupt:
                log.warning("render: Aborting")
                for f in fs:
                    f.cancel()
                raise

            results = list(f.result() for f in waited_fs.done)
    else:
        results = list(RenderResult(repo.workdir) for repo in repos)

    log.debug("render: Sorting results")
    reverse = bool(options & RenderOptions.REVERSE)
    if options & RenderOptions.COMMIT_TIME:
        results.sort(key=lambda r: r.commit_time, reverse=not reverse)
    else:
        results.sort(key=lambda r: r.path, reverse=reverse)

    for line in RenderResults(results, options):
        print(line)
