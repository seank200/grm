import concurrent.futures
import enum
import logging
import pygit2

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .config import relative_workdir


log = logging.getLogger(__name__)


class RenderFormat(enum.Enum):
    RELATIVE = enum.auto()
    ABSOLUTE = enum.auto()
    LONG = enum.auto()


@dataclass
class RenderCache:
    path: str
    index: bool = False
    worktree: bool = False
    untracked: bool = False
    ahead: bool = False
    behind: bool = False
    conflicted: bool = False
    detached: bool = False

    head: str = ""
    upstream: str = ""
    last_modified: Optional[datetime] = None

    def __str__(self) -> str:
        s = ""
        s += "i" if self.index else "-"
        s += "w" if self.worktree else "-"
        s += "u" if self.untracked else "-"
        s += "a" if self.ahead else "-"
        s += "b" if self.behind else "-"
        s += "c" if self.conflicted else "-"
        s += "d" if self.detached else "-"
        s += " "
        s += self.head if self.head else "-"
        s += "\t"
        s += self.upstream if self.upstream else "-"
        s += "\t"
        s += (
            self.last_modified.strftime("%b %d %H:%M")
            if self.last_modified
            else "--- -- --:--"
        )
        s += " "
        s += self.path
        return s


def _render_status(path: str):
    repo = pygit2.Repository(path)
    repo.status(untracked_files="normal")
    return RenderCache(path)


def _render_repos_long(repos: list[pygit2.Repository]):
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        fs = tuple(executor.submit(_render_status, repo.path) for repo in repos)
        waited_fs = concurrent.futures.wait(fs, timeout=10.0)
        results = tuple(f.result() for f in waited_fs.done)

    for result in results:
        print(str(result))


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

    _render_repos_long(repos)
