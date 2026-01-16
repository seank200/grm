import logging
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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
    ahead: int = 0
    behind: int = 0


@dataclass
class GitCommit:
    commit_hash: str
    subject: str
    author_date: datetime


@dataclass
class GitHead:
    branch: Optional[GitBranch] = None
    commit: Optional[GitCommit] = None


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
    operation: Optional[GitOperation] = None
    """Interactive git operation currently in progress"""

    @property
    def ahead(self) -> int:
        return 0 if self.head.branch is None else self.head.branch.ahead
    
    @property
    def behind(self) -> int:
        return 0 if self.head.branch is None else self.head.branch.behind

    def concise(self) -> str:
        """
        Return a concise representation of repository status (iwuabc)
        - i: index
        - w: working tree
        - u: untracked
        - a: ahead
        - b: behind
        - c: conflict(unmerged)
        """
        s = ""

        s += "i" if self.index > 0 else "-"
        s += "w" if self.work_tree > 0 else "-"
        s += "u" if self.untracked > 0 else "-"

        if self.head.branch and self.head.branch.upstream:
            s += "a" if self.head.branch.ahead > 0 else "-"
            s += "b" if self.head.branch.behind > 0 else "-"
        else:
            s += "--"

        s += "c" if (self.unmerged > 0 or self.operation is not None) else "-"

        return s


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

        try:
            proc = self.run(args)
            self._status = None
        except subprocess.CalledProcessError as e:
            log.error("('%s') ERROR: Failed to switch to '%s' (%d).\n%s",
                      self.name, branch, e.returncode, e.stderr)
            raise

        log.info("('%s') Switched to '%s'", self.name, branch)
        return proc
    
    def fetch(
        self,
        repository: str = "",
        *,
        all: bool = False,
        prune: bool = False,
        prune_tags: bool = False,
        refetch: bool = False,
        tags: bool = False,
        quiet: bool = False,
        verbose: bool = False,
    ):
        args = ["git", "fetch"]

        if repository and all:
            raise ValueError("Cannot set both 'repository' and 'all'")
        
        if quiet and verbose:
            raise ValueError("Cannot set both 'quiet' and 'verbose'")

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
        if quiet:
            args.append("--quiet")
        if verbose:
            args.append("--verbose")

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
            log.error("(%s) Failed to fetch %s (%d).\n%s", self.name, l_repository, e.returncode, e.stderr)
            raise

        self._status = None

        stdout = ("\n" + proc.stdout) \
            if (proc.stdout and proc.stdout.rstrip("\n")) else ""
        stderr = ("\n" + proc.stderr) \
            if (proc.stderr and proc.stderr.rstrip("\n")) else ""

        log.info("(%s) Fetched %s. %s %s", self.name, l_repository, stdout, stderr)


    def push(self):
        try:
            proc = self.run(("git", "push"))
        except subprocess.CalledProcessError as e:
            log.error("(%s) Failed to push (%d).\n%s", self.name, e.returncode, e.stderr)
            raise

        stdout = ("\n" + proc.stdout) \
            if (proc.stdout and proc.stdout.rstrip("\n")) else ""
        stderr = ("\n" + proc.stderr) \
            if (proc.stderr and proc.stderr.rstrip("\n")) else ""

        log.info("(%s) Pushed to remote. %s %s", self.name, stdout, stderr)
        return proc
    
    def merge(
        self,
        commit: str,
        *,
        ff: Optional[bool] = None,
        ff_only: Optional[bool] = None,
        message: Optional[str] = None,
        log_count: Optional[int] = None,
        quiet: bool = False,
        verbose: bool = False,
    ):
        if ff is not None and ff_only is not None:
            raise ValueError("Cannot set both ff and ff_only")
        
        if not commit:
            raise ValueError("commit must be specified")
        
        if quiet and verbose:
            raise ValueError("Cannot set both quiet and verbose")
        
        args = ["git", "merge"]

        if ff is True:
            args.append("--ff")
        elif ff is False:
            args.append("--no-ff")

        if ff_only is True:
            args.append("--ff-only")

        if message:
            args.append("-m")
            args.append(message)

        if log_count:
            args.append(f"--log={log_count}")

        if quiet:
            args.append("--quiet")

        if verbose:
            args.append("--verbose")

        args.append(commit)

        try:
            proc = self.run(args)
        except subprocess.CalledProcessError as e:
            log.error("(%s) Failed to merge '%s' (%d). %s", self.name, commit, e.returncode, e.stderr)
            raise

        self._status = None

        stdout = ("\n" + proc.stdout) \
            if (proc.stdout and proc.stdout.rstrip("\n")) else ""
        stderr = ("\n" + proc.stderr) \
            if (proc.stderr and proc.stderr.rstrip("\n")) else ""

        log.info("(%s) Merged '%s'. %s %s", self.name, commit, stdout, stderr)


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
                log.error("(%s) %s", self.path, e.stderr)
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

        if not no_commits_yet:
            try:
                proc = self.run(("git", "log", "-n", "1", "--format=%H..%aI..%s"))

                head_commit_out = proc.stdout
                hash_end = head_commit_out.index("..")
                commit_hash = head_commit_out[:hash_end]
                
                author_date_start = hash_end + 2
                author_date_end = head_commit_out.index("..", author_date_start)
                author_date = datetime.fromisoformat(head_commit_out[author_date_start:author_date_end])

                subject = head_commit_out[author_date_end + 2:].rstrip("\n")

                head.commit = GitCommit(
                    commit_hash=commit_hash,
                    author_date=author_date,
                    subject=subject
                )
            except subprocess.CalledProcessError as e:
                log.error("Failed to read HEAD commit metadata of '%s'. %s", self.path, e.stderr)

        if self.path.joinpath(".git", "rebase-merge").is_dir() \
            or self.path.joinpath(".git", "rebase-apply").is_dir():
            status.operation = GitOperation.REBASE
        elif self.path.joinpath(".git", "MERGE_HEAD").is_file():
            status.operation = GitOperation.MERGE
        elif self.path.joinpath(".git", "CHERRY_PICK_HEAD").is_file():
            status.operation = GitOperation.CHERRY_PICK
        elif self.path.joinpath(".git", "REVERT_HEAD").is_file():
            status.operation = GitOperation.REVERT
        elif self.path.joinpath(".git", "BISECT_LOG").is_file():
            status.operation = GitOperation.BISECT
        elif self.path.joinpath(".git", "sequencer").is_dir():
            status.operation = GitOperation.SEQUENCER

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
        