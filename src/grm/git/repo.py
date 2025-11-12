import logging
import os
from ..exceptions import CommandError, InvalidOptsError
from .branch import GitBranch, list_branches
from .fetch import fetch
from .log import git_log, COMPACT
from .merge import merge_ff
from .push import push
from .remote import GitRemote, list_remotes
from .status import GitStatus, show_status
from .switch import switch
from pathlib import Path
from rich.text import Text
from typing import Optional


SEP = os.sep
log = logging.getLogger(__name__)


class GitRepo:
    def __init__(self, path: Path):
        self.path: Path = path
        self._remotes: Optional[dict[str, GitRemote]] = None
        self._status: Optional[GitStatus] = None
        self._branches: Optional[list[GitBranch]] = None

    @property
    def name(self) -> str:
        return self.path.name
    
    @property
    def remotes(self) -> dict[str, GitRemote]:
        if self._remotes is None:
            self._remotes = list_remotes(self.path)
        return self._remotes
    
    @property
    def status(self) -> GitStatus:
        if self._status is None:
            self._status = show_status(self.path)
        return self._status

    @property
    def branches(self) -> list[GitBranch]:
        if self._branches is None:
            self._branches = list_branches(self.path)
        return self._branches
    
    def switch(self, refname: str, *, detach: bool):
        status = self.status
        if status.not_staged + status.staged > 0:
            raise CommandError(
                "Cannot switch {} to '{}'. Working tree contains changes"
                    .format(self.name, refname)
            )

        switch(self.path, refname, detach=detach)
        self._status = None
        self._branches = None
        log.info("Switched %s to '%s'", self.name, refname)
    
    def fetch(
        self,
        remote: Optional[str] = None,
        *,
        all: bool = False,
        prune: bool = False
    ):
        f_remote = remote if remote else "all" if all else "~"
        log.info("Fetching %s (%s)", self.name, f_remote)
        fetch(self.path, remote, all=all, prune=prune)
        self._status = None
        self._branches = None
        log.debug("Fetched %s (%s)", self.name, f_remote)

    def current_branch(self) -> GitBranch:
        branch = self.status.parsed_branch
        if branch is None:
            if self.status.is_detached():
                cause = "HEAD is detached."
            elif self.status.no_commits():
                cause = "No commits on current branch."
            else:
                cause = "Invalid status"
            raise CommandError(cause)
        return branch

    def merge_ff(self, commit: str):
        if not commit:
            raise InvalidOptsError("Merge target commit is required")

        branch = self.current_branch()

        if branch.ahead > 0 and branch.behind > 0:
            raise CommandError(
                "Cannot fast-forward due to diverged history. (ahead {}, behind {})" \
                    .format(self.name, branch.ahead, branch.behind)
            )

        log.info(
            "Merging %s: %s <- %s (behind %d, fast-forward)",
            self.name,
            branch.name,
            branch.upstream,
            branch.behind
        )
        merge_ff(self.path, commit)
        self._status = None
        self._branches = None
        log.debug(
            "Merged %s: %s <- %s (fast-forward)",
            self.name,
            branch.name,
            branch.upstream
        )

    def push(self):
        branch = self.current_branch()
        if branch.upstream is None:
            raise CommandError(f"Branch '{branch.name}' has no remote-tracking branch.")

        log.info("Pushing %s (%s -> %s)", self.name, branch.name, branch.upstream)
        push(self.path)
        self._status = None
        self._branches = None
        log.debug("Pushed %s (%s -> %s)", self.name, branch.name, branch.upstream)

    def log(self, format: str = "", max_count: int = -1) -> list[str]:
        return git_log(self.path, format, max_count)

    def render_name(self) -> Text:
        return Text(self.name, style="bold cyan")

    def render_path(self, root: Optional[Path] = None) -> Text:
        if root is None:
            path = str(self.path)
        else:
            path = str(self.path.relative_to(root))
            if path == ".":
                path = self.path.name
        
        text = Text(path)
        text.stylize("bold cyan", start=len(text)-len(self.path.name))

        return text

    def render_remotes(self, *, short: bool = False, sep: str = "\n") -> Text:
        if not self.remotes:
            return Text("~", style="red")

        text = Text()
        show_name = len(self.remotes) > 1
        for remote in self.remotes.values():
            if text:
                text.append(sep)
            text.append(remote.render(short=short, show_name=show_name))
        return text

    def render_head(self) -> str:
        logs = self.log(COMPACT)
        if logs:
            return logs[0]
        return ""
