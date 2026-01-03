import os
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Optional
from .remote import get_remotes, GitRemote


class GitRepo:
    @staticmethod
    def run(repos: Collection['GitRepo'], *, remotes: bool = False):
        if len(repos) <= 2:
            for repo in repos:
                repo._run(
                    remotes=remotes
                )
            return

        max_workers = min(8, len(repos), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(lambda r: r._run(
                remotes=remotes,
            ), repos, timeout=60.0)

    def __init__(self, path: Path):
        self.path: Path = path
        """Local repository path"""

        self._remotes: Optional[list[GitRemote]] = None

    def remotes(self) -> list[GitRemote]:
        if self._remotes is None:
            self._remotes = get_remotes(self.path)
        return self._remotes

    def _run(self, remotes: bool):
        if remotes:
            self.remotes()