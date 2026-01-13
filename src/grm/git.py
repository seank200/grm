import logging
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from rich.text import Text
from typing import Optional, Union
from .config import get_config


type StrOrBytesPath = Union[str, bytes, os.PathLike[str], os.PathLike[bytes], Sequence[Union[str, bytes, os.PathLike[str], os.PathLike[bytes]]]]

NO_COMMIT = "(initial)"
NO_BRANCH = "(detached)"
RE_AHEAD = re.compile(r"\+([0-9]+)")
RE_BEHIND = re.compile(r"-([0-9]+)")
RUN_TIMEOUT = 60.0

log = logging.getLogger(__name__)



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
    stashed: int = 0
    tracked: int = 0
    untracked: int = 0
    unmerged: int = 0


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
        return status.tracked + status.unmerged == 0
    
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
        if self._status is None:
            try:
                proc = self.run(["git", "status", "--porcelain=v2", "--branch"])
            except subprocess.CalledProcessError as e:
                log.error("Failed to check status of '%s'. %s",
                          self.path, e.stderr)
                raise

            status = GitStatus(GitHead())
            head = status.head

            for line in proc.stdout.splitlines():
                if line.startswith("# branch.oid "):
                    oid = line[len("# branch.oid "):]
                    if oid != NO_COMMIT:
                        head.oid = oid

                elif line.startswith("# branch.head "):
                    branch_name = line[len("# branch.head "):]
                    if branch_name != NO_BRANCH:
                        head.branch = GitBranch(branch_name)

                elif line.startswith("# branch.upstream "):
                    if head.branch is not None:
                        head.branch.upstream = line[len("# branch.upstream "):]

                elif line.startswith("# branch.ab "):
                    start = len("# branch.ab ")

                    if head.branch is not None:
                        try:
                            m_ahead = RE_AHEAD.search(line, start)
                            if m_ahead:
                                head.branch.ahead = int(m_ahead.group(1))
                            
                            m_behind = RE_BEHIND.search(line, start)
                            if m_behind:
                                head.branch.behind = int(m_behind.group(1))
                        except ValueError:
                            log.warning("(%s) Invalid git-status line: %s",
                                        self.path, line)
                            head.branch.ahead = -1
                            head.branch.behind = -1

                elif line.startswith("# stash "):
                    try:
                        status.stashed = int(line[len("# stash "):])
                    except ValueError:
                        log.warning("(%s) Invalid git-status line: %s",
                                    self.path, line)
                        status.stashed = -1

                elif line.startswith("1 ") or line.startswith("2 "):
                    status.tracked += 1

                elif line.startswith("u "):
                    status.unmerged += 1

                elif line.startswith("? "):
                    status.untracked += 1

                else:
                    log.debug("(%s) Ignoring git-status line: %s",
                                self.path, line)

            self._status = status
        
        return self._status

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