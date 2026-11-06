from collections.abc import Collection
from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
from typing import ClassVar, Optional

from grm.util import GrmException, run_cmd


log = logging.getLogger(__name__)


class GitException(GrmException):
    def __init__(self, path: Path, *args):
        super().__init__(*args)
        self.path = path


@dataclass
class GitBranch:
    name: str
    is_head: bool = False
    upstream: str | None = None
    track: str | None = None

    REF_FORMAT: ClassVar[str] = \
        "%(HEAD)%(refname:short):%(upstream:short):%(upstream:trackshort)"

    @staticmethod
    def parse(line: str):
        is_head = line[0] == "*"
        name, upstream, track = line[1:].split(":")

        return GitBranch(
            name=name,
            is_head=is_head,
            upstream=upstream or None,
            track=track or None,
        )


@dataclass
class GitRemote:
    name: str
    url: str


@dataclass
class GitWorktree:
    path: Path
    head: str
    branch: str | None = None
    prunable: bool = False
    locked: bool = False
    bare: bool = False

    @staticmethod
    def parse(lines: Collection[str]):
        attribs: dict[str, str] = {}
        for line in lines:
            parts = line.split(" ")
            k = parts[0]
            v = parts[1] if len(parts) > 1 else ""
            attribs[k] = v

        return GitWorktree(
            path=Path(attribs["path"]),
            head=attribs["head"],
            branch=attribs.get("branch"),
            prunable="prunable" in attribs,
            locked="locked" in attribs,
            bare="bare" in attribs,
        )


class GitRepository:
    @staticmethod
    def clone(url: str, path: Path) -> "GitRepository":
        log.info("Cloning '%s' (%s)", url, path)
        try:
            proc = run_cmd(None, ("git", "clone", url, path))
        except subprocess.CalledProcessError as exc:
            raise GitException(path, f"Failed to clone '{url}'") from exc

        log.debug("Cloned '%s' (%s). %s", url, path, proc.stdout)

        return GitRepository(path)

    def __init__(self, path: Path):
        self.path = path
        self._worktrees: Optional[list[GitWorktree]] = None
        self._branches: Optional[list[GitBranch]] = None
        self._remote_names: Optional[list[str]] = None
        self._remotes: Optional[list[GitRemote]] = None

    @property
    def name(self) -> str:
        return self.path.name

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, value):
        return isinstance(value, GitRepository) and self.path == value.path

    def resolve(self) -> 'GitRepository':
        worktree = self.main_worktree()
        if worktree is None:
            return self

        if self.path == worktree.path:
            return self

        return GitRepository(worktree.path)

    def list_worktrees(self, *, cache: bool = True) -> list[GitWorktree]:
        if cache and self._worktrees is not None:
            return self._worktrees

        try:
            proc = run_cmd(
                self.path,
                ("git", "worktree", "list", "--porcelain")
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(self.path, "Failed to list worktrees") from exc

        worktrees: list[GitWorktree] = []
        for lines in proc.stdout.rstrip("\n").split("\n\n"):
            worktrees.append(GitWorktree.parse(lines))

        return worktrees

    def main_worktree(self) -> Optional[GitWorktree]:
        worktrees = self.list_worktrees()
        try:
            return worktrees[0]
        except IndexError:
            return None

    def list_branches(self, *, cache: bool = True) -> list[GitBranch]:
        if cache and self._branches is not None:
            return self._branches

        try:
            proc = run_cmd(
                self.path,
                (
                    "git",
                    "branch",
                    "--format", GitBranch.REF_FORMAT
                )
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(self.path, "Failed to list branches") from exc

        branches: list[GitBranch] = []
        for line in proc.stdout.splitlines():
            if not line:
                continue

            branches.append(GitBranch.parse(line))

        return branches

    def current_branch(self) -> Optional[GitBranch]:
        for branch in self.list_branches():
            if branch.is_head:
                return branch

    def list_remotes(self, *, cache: bool = True) -> list[GitRemote]:
        if cache and self._remotes is not None:
            return self._remotes

        remotes: list[GitRemote] = []
        for name in self.list_remote_names():
            try:
                proc = run_cmd(self.path, ("git", "remote", "get-url", name))
            except subprocess.CalledProcessError as exc:
                raise GitException(
                    self.path,
                    "Failed to list remotes",
                ) from exc

            url = proc.stdout.rstrip("\n")
            remotes.append(GitRemote(name=name, url=url))

        self._remotes = remotes
        return remotes

    def list_remote_names(self, *, cache: bool = True) -> list[str]:
        if cache and self._remote_names is not None:
            return self._remote_names

        try:
            proc = run_cmd(self.path, ("git", "remote"))
        except subprocess.CalledProcessError as exc:
            raise GitException(self.path, "Failed to list remote names") from exc

        remote_names = [line.strip() for line in proc.stdout.splitlines() if line]
        self._remote_names = remote_names
        return remote_names
