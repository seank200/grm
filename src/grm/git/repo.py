import logging
from .fetch import fetch
from .pull import pull_ff
from .remote import GitRemote, list_remotes
from .status import GitStatus, show_status
from .switch import switch_to
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


class GitRepo:
    def __init__(self, path: Path):
        self.path: Path = path
        self._remotes: Optional[dict[str, GitRemote]] = None
        self._status: Optional[GitStatus] = None

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
    
    def switch(self, refname: str, *, detach: bool):
        switch_to(self.path, refname, detach=detach)
        self._status = None
    
    def fetch(self, all: bool = False, prune: bool = False):
        fetch(self.path, all, prune)
        self._status = None

    def pull_ff(self):
        pull_ff(self.path)
