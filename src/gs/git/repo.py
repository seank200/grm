from .remote import GitRemote, list_remotes
from .status import GitStatus, show_status
from pathlib import Path
from typing import Optional


class Repo:
    def __init__(self, path: Path):
        self.path: Path = path
        self._remotes: Optional[dict[str, GitRemote]] = None
        self._status: Optional[GitStatus] = None

    @property
    def name(self) -> str:
        return self.path.name
    
    def remotes(self) -> dict[str, GitRemote]:
        if self._remotes is None:
            self._remotes = list_remotes(self.path)
        return self._remotes
    
    def status(self) -> GitStatus:
        if self._status is None:
            self._status = show_status(self.path)
        return self._status
    