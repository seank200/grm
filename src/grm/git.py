from dataclasses import dataclass
import logging
from pathlib import Path, PurePath
import subprocess
from typing import ClassVar, Optional

from grm.util import GrmException, run_cmd


CLONE_TIMEOUT = 30.0
FETCH_TIMEOUT = 16.0

log = logging.getLogger(__name__)


class GitException(GrmException):
    def __init__(self, path: Path, *args):
        super().__init__(*args)
        self.path = path

    def __str__(self):
        if not isinstance(self.__cause__, subprocess.CalledProcessError):
            return super().__str__()

        return f"{super().__str__()}.\n{self.__cause__.stderr}".rstrip("\n")


@dataclass
class GitBranch:
    name: str
    is_head: bool = False
    upstream: str | None = None
    track: str | None = None

    REF_FORMAT: ClassVar[str] = \
        "%(HEAD)%(refname):%(upstream):%(upstream:trackshort)"

    @staticmethod
    def parse(line: str) -> Optional["GitBranch"]:
        is_head = line[0] == "*"
        name, upstream, track = line[1:].split(":")

        if name.startswith("refs/"):
            return GitBranch(
                name=name,
                is_head=is_head,
                upstream=upstream or None,
                track=track or None,
            )

    @property
    def name_short(self) -> str:
        return self.name[self.name.find("/", 5)+1:]

    @property
    def upstream_short(self) -> Optional[str]:
        if self.upstream is None:
            return None

        return self.upstream[self.upstream.find("/", 5)+1:]


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
    def parse(lines: str):
        attribs: dict[str, str] = {}
        for line in lines.splitlines():
            parts = line.split(" ")
            k = parts[0]
            v = parts[1] if len(parts) > 1 else ""
            attribs[k] = v

        return GitWorktree(
            path=Path(attribs["worktree"]),
            head=attribs["HEAD"],
            branch=attribs.get("branch"),
            prunable="prunable" in attribs,
            locked="locked" in attribs,
            bare="bare" in attribs,
        )


class GitRepository:
    @staticmethod
    def clone(url: str, path: Path) -> "GitRepository":
        log.debug("Cloning '%s' (%s)", url, path)
        try:
            run_cmd(
                None,
                ("git", "clone", url, str(path)),
                timeout=CLONE_TIMEOUT
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(path, f"Failed to clone '{url}'") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitException(
                path,
                f"Failed to clone '{url}'. Operation timed out "
                f"(after {exc.timeout}s)"
            )

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

    def clear_cache(
        self,
        *,
        worktree: bool = True,
        branch: bool = True,
        remote: bool = True,
    ):
        if worktree:
            self._worktrees = None
        if branch:
            self._branches = None
        if remote:
            self._remote_names = None
            self._remotes = None

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

    def create_worktree(self, path: PurePath, ref: str) -> GitWorktree:
        worktree_path = (self.path / path).resolve()

        try:
            run_cmd(
                self.path,
                ("git", "worktree", "add", str(worktree_path), ref)
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(
                self.path,
                "Failed to create worktree '{}' ({})".format(
                    worktree_path,
                    ref,
                )
            ) from exc

        self.clear_cache(worktree=True, branch=False, remote=False)
        for worktree in self.list_worktrees():
            if worktree.path == worktree_path:
                return worktree

        raise GitException(
            self.path,
            "Failed to create worktree '{}' ({})".format(
                worktree_path,
                ref
            )
        )

    def prune_worktrees(self):
        try:
            run_cmd(self.path, ("git", "worktree", "prune"))
        except subprocess.CalledProcessError as exc:
            raise GitException(self.path, "Failed to prune worktrees") from exc

        self.clear_cache(worktree=True, branch=False, remote=False)

    def remove_worktree(self, worktree: GitWorktree):
        try:
            run_cmd(
                self.path,
                ("git", "worktree", "remove", str(worktree.path)),
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(
                self.path,
                f"Failed to remove worktree '{worktree.path}'"
            ) from exc

    def list_branches(
        self,
        *,
        cache: bool = True,
        worktree: GitWorktree | None = None,
    ) -> list[GitBranch]:
        if cache and self._branches is not None:
            return self._branches

        try:
            proc = run_cmd(
                worktree.path if worktree else self.path,
                (
                    "git",
                    "branch",
                    "--format", GitBranch.REF_FORMAT
                )
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(
                worktree.path if worktree else self.path,
                "Failed to list branches"
            ) from exc

        branches: list[GitBranch] = []
        for line in proc.stdout.splitlines():
            if not line:
                continue

            branch = GitBranch.parse(line)
            if branch is not None:
                branches.append(branch)

        return branches

    def current_branch(
        self,
        *,
        cache: bool = True,
        worktree: GitWorktree | None = None,
    ) -> Optional[GitBranch]:
        for branch in self.list_branches(cache=cache, worktree=worktree):
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
            raise GitException(
                self.path,
                "Failed to list remote names"
            ) from exc

        remote_names = [
            line.strip()
            for line in proc.stdout.splitlines()
            if line
        ]
        self._remote_names = remote_names
        return remote_names

    def fetch(
        self,
        remote_name: str = "",
        *,
        all: bool = False,
        prune: bool = False,
        tags: bool | None = None,
        prune_tags: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        args = ["git", "fetch"]
        if all:
            args.append("--all")
        elif remote_name:
            args.append(remote_name)
        if prune:
            args.append("--prune")
        if tags is True:
            args.append("--tags")
        elif tags is False:
            args.append("--no-tags")
        if prune_tags:
            args.append("--prune-tags")

        try:
            proc = run_cmd(
                self.path,
                args,
                timeout=FETCH_TIMEOUT,
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(
                self.path,
                f"Failed to fetch {remote_name or 'remote'}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitException(
                self.path,
                f"Failed to fetch {remote_name or 'remote'}. "
                f"Operation timed out (after {exc.timeout}s)"
            )

        self.clear_cache()
        return proc

    def merge(
        self,
        ref: str,
        *,
        ff: bool | None = None,
        ff_only: bool = False,
        worktree: GitWorktree | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = ["git", "merge"]
        if ff is True:
            args.append("--ff")
        elif ff is False:
            args.append("--no-ff")
        elif ff_only:
            args.append("--ff-only")
        args.append(ref)

        try:
            proc = run_cmd(
                worktree.path if worktree else self.path,
                args
            )
        except subprocess.CalledProcessError as exc:
            raise GitException(
                worktree.path if worktree else self.path,
                f"Failed to merge '{ref}'"
            ) from exc

        self.clear_cache()
        return proc
