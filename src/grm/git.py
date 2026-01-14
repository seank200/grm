import logging
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from rich.text import Text
from typing import Optional, Union
from .config import get_config


type StrOrBytesPath = Union[str, bytes, os.PathLike[str], os.PathLike[bytes], Sequence[Union[str, bytes, os.PathLike[str], os.PathLike[bytes]]]]

NO_COMMIT = "No commits yet on "
DETACHED = "HEAD (no branch)"
RE_AHEAD = re.compile(r"ahead ([0-9]+)")
RE_BEHIND = re.compile(r"behind ([0-9]+)")
RUN_TIMEOUT = 60.0
UNMERGED_STATUS = set((
    "DD",  # unmerged, both deleted
    "AU",  # unmerged, added by us
    "UD",  # unmerged, deleted by them
    "UA",  # unmerged, added by them
    "DU",  # unmerged, deleted by us
    "AA",  # unmerged, both added
    "UU",  # unmerged, both modified
))

log = logging.getLogger(__name__)


class GitOperation(Enum):
    MERGE = "merge"
    REBASE = "rebase"
    CHERRY_PICK = "cherry-pick"
    REVERT = "revert"
    BISECT = "bisect"
    SEQUENCER = "sequencer"


@dataclass
class GitBranch:
    name: str
    is_head: bool = False
    upstream: Optional[str] = None
    ahead: int = -1
    behind: int = -1


@dataclass
class GitHead:
    oid: Optional[str] = None
    branch: Optional[GitBranch] = None


@dataclass
class GitStatus:
    head: GitHead
    index: int = 0
    """Number of changes in index (added)"""
    work_tree: int = 0
    """Number of changes in working tree"""
    untracked: int = 0
    """Number of untracked objects"""
    unmerged: int = 0
    """Number of unmerged objects"""
    in_progress: Optional[GitOperation] = None
    """Interactive git operation currently in progress"""


@dataclass
class GitRemote:
    name: str
    url: str


class GitRepo:
    RUN_TIMEOUT: float = 60.0

    def __init__(self, path: Path):
        self.path = path
        self._remotes: Optional[dict[str, GitRemote]] = None
        self._status: Optional[GitStatus] = None

    @property
    def name(self):
        return self.path.name
    
    def switch(self, branch: str, *, detach: bool = False):
        args = ["git", "switch"]
        if detach:
            args.append("--detach")
        if not branch:
            raise ValueError("refspec cannot be empty")
        args.append(branch)

        return self.run(args)
    
    def fetch(
        self,
        repository: str = "",
        *,
        all: bool = False,
        prune: bool = False,
        prune_tags: bool = False,
        refetch: bool = False,
        tags: bool = False,
    ):
        args = ["git", "fetch"]

        if repository and all:
            raise ValueError("Cannot set both 'repository' and 'all'")

        if all:
            args.append("-a")
        if prune:
            args.append("-p")
        if prune_tags:
            args.append("-P")
        if refetch:
            args.append("--refetch")
        if tags:
            args.append("-t")

        if repository:
            args.append(repository)

        # Prepare logging
        if repository:
            l_repository = repository
        elif all:
            l_repository = "all remotes"
        else:
            l_repository = "remote"

        try:
            proc = self.run(args)
        except subprocess.CalledProcessError as e:
            log.error("Failed to fetch %s of '%s'.\n%s", l_repository, self.path, e.stderr)
            raise

        self._status = None

        if log.isEnabledFor(logging.DEBUG):
            stdout = ("\n" + proc.stdout) \
                if (proc.stdout and proc.stdout.rstrip("\n")) else ""
            stderr = ("\n" + proc.stderr) \
                if (proc.stderr and proc.stderr.rstrip("\n")) else ""
        else:
            stdout = ""
            stderr = ""

        log.info("Fetched %s of '%s'. %s %s", l_repository, self.path, stdout, stderr)

    
    def ff_upstream(self):
        """Fast-forward merge remote-tracking branch"""

        if not self.is_clean():
            raise RuntimeError("Cannot fast-forward '{}'. Working tree is not clean.".format(self.path))
        
        status = self.status()
        branch = status.head.branch
        
        if branch is None:
            raise RuntimeError("Cannot fast-forward '{}'. HEAD is detached.".format(self.path))

        if branch.upstream is None:
            raise RuntimeError("Branch '{}' of '{}' has no remote-tracking branch.".format(branch.name, self.path))
        
        try:
            proc = self.run(["git", "merge", "--ff-only", branch.upstream])
        except subprocess.CalledProcessError as e:
            log.error("Failed to fast-forward '%s' into '%s' of '%s'.\n%s",
                      branch.upstream, branch.name, self.path, e.stderr)
            raise

        self._status = None

        if log.isEnabledFor(logging.DEBUG):
            stdout = ("\n" + proc.stdout) \
                if (proc.stdout and proc.stdout.rstrip("\n")) else ""
            stderr = ("\n" + proc.stderr) \
                if (proc.stderr and proc.stderr.rstrip("\n")) else ""
        else:
            stdout = ""
            stderr = ""

        log.info("Fast-forwarded '%s' into '%s' of '%s'. %s %s",
                 branch.upstream, branch.name, self.path, stdout, stderr)


    def is_clean(self) -> bool:
        status = self.status()
        return status.index + status.work_tree + status.unmerged == 0
    
    def get_remotes(self) -> dict[str, GitRemote]:
        if self._remotes is None:
            self._remotes = {}
            proc = self.run("git remote --verbose".split(" "))

            for line in proc.stdout.splitlines():
                try:
                    name_end = line.index("\t")
                    name = line[:name_end]

                    if name in self._remotes:
                        continue

                    url_end = line.index(" ", name_end+1)
                    url = line[name_end+1:url_end]

                    self._remotes[name] = GitRemote(name=name, url=url)
                except ValueError:
                    log.error("Invalid git-remote output: %s (%s)", line, self.path)
        
        return self._remotes
    
    def get_remote_url(self, name: str) -> str:
        remote = self.get_remotes().get(name)
        return "" if remote is None else remote.url
    
    def set_remote_url(self, name: str, url: str):
        if not name:
            raise ValueError("Remote name cannot be empty")
        if not url:
            raise ValueError("Remote URL cannot be empty")
        
        try:
            self.run(["git", "remote", "set-url", name, url])
        except subprocess.CalledProcessError as e:
            if e.returncode == 2:
                log.error("%s (%s)", e.stderr, self.path)
            raise

        self._remotes = None
        self._status = None

    def status(self) -> GitStatus:
        if self._status is not None:
            return self._status

        try:
            proc = self.run(["git", "status", "--porcelain", "--branch"])
        except subprocess.CalledProcessError as e:
            log.error("Failed to check status of '%s'. %s",
                        self.path, e.stderr)
            raise

        head = GitHead()
        status = GitStatus(head)
        no_commits_yet = False

        for line in proc.stdout.splitlines():
            if line.startswith("## "):
                # main...origin/main [behind 8]
                name_start = 3
                name_end = line.find("...", name_start)
                if name_end < 0:
                    name = line[name_start:]
                else:
                    name = line[name_start:name_end]

                if name.startswith(NO_COMMIT):
                    no_commits_yet = True
                    continue

                if name.startswith(DETACHED):
                    continue

                branch = GitBranch(name=name, is_head=True)
                head.branch = branch

                if name_end < 0:
                    continue

                branch.ahead = 0
                branch.behind = 0

                upstream_start = name_end + 3
                upstream_end = line.find(" [", upstream_start)
                if upstream_end < 0:
                    branch.upstream = line[upstream_start:]
                    continue
                branch.upstream = line[upstream_start:upstream_end]

                ab_start = upstream_end + 2
                a_match = RE_AHEAD.search(line, ab_start)
                if a_match:
                    branch.ahead = int(a_match.group(1))
                b_match = RE_BEHIND.search(line, ab_start)
                if b_match:
                    branch.behind = int(b_match.group(1))
            elif line.startswith("??"):
                status.untracked += 1
            else:
                xy = line[0:2]
                if xy in UNMERGED_STATUS:
                    status.unmerged += 1
                else:
                    if xy[0] != " ":
                        status.index += 1
                    if xy[1] != " ":
                        status.work_tree += 1

        if head.branch is None and not no_commits_yet:
            try:
                proc = self.run(("git", "rev-parse", "HEAD"))
            except subprocess.CalledProcessError as e:
                log.error("Failed to read refname of HEAD. %s", e.stderr)
                raise

            head.oid = proc.stdout.rstrip("\n")

        if self.path.joinpath(".git", "rebase-merge").is_dir() \
            or self.path.joinpath(".git", "rebase-apply").is_dir():
            status.in_progress = GitOperation.REBASE
        elif self.path.joinpath(".git", "MERGE_HEAD").is_file():
            status.in_progress = GitOperation.MERGE
        elif self.path.joinpath(".git", "CHERRY_PICK_HEAD").is_file():
            status.in_progress = GitOperation.CHERRY_PICK
        elif self.path.joinpath(".git", "REVERT_HEAD").is_file():
            status.in_progress = GitOperation.REVERT
        elif self.path.joinpath(".git", "BISECT_LOG").is_file():
            status.in_progress = GitOperation.BISECT
        elif self.path.joinpath(".git", "sequencer").is_dir():
            status.in_progress = GitOperation.SEQUENCER

        self._status = status
        return self._status
    
    def head(self) -> GitHead:
        return self.status().head

    def run(self, args: StrOrBytesPath, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            proc = subprocess.run(
                args,
                cwd=self.path,
                capture_output=True,
                check=check,
                encoding="utf-8",
                text=True,
                timeout=RUN_TIMEOUT,
            )

            if proc.returncode != 0:
                log.debug("Subprocess failed (%d) '%s' %s. %s", proc.returncode,
                          self.path, args, proc.stderr)

            return proc
        except subprocess.TimeoutExpired:
            log.error("Subprocess timed out after %f seconds. '%s' %s",
                      RUN_TIMEOUT, self.path, args)
            raise
        except subprocess.CalledProcessError as e:
            log.debug("Subprocess failed (%d) '%s' %s. %s", e.returncode,
                      self.path, args, e.stderr)
            raise