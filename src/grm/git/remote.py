import logging
import re
from dataclasses import dataclass
from grm.utils import run
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


@dataclass
class GitRemote:
    name: str
    fetch: Optional[str] = None
    push: Optional[str] = None

    _fetch_path: Optional[str] = None

    @property
    def fetch_path(self) -> Optional[str]:
        if self.fetch is None:
            return None
        
        if self._fetch_path is None:
            self._fetch_path = urlparse(self.fetch).path

        return self._fetch_path
    
    def __str__(self):
        return f"GitRemote(" \
            + f"name='{self.name}', " \
            + f"fetch='{self.fetch}', " \
            + f"push='{self.push}'" \
            + ")"


PATTERN = re.compile(r"^(\S+)\s+(\S+)\s+\((\S+)\)")

log = logging.getLogger(__name__)


def list_remotes(path: Path) -> dict[str, GitRemote]:
    args = "git remote -v".split(" ")
    proc = run(args, path)

    if not proc.stdout:
        return {}
    
    remotes: dict[str, GitRemote] = {}

    for line in proc.stdout.splitlines():
        m = re.match(PATTERN, line)
        if m is None:
            log.warning("Ignoring invalid git remote output line: %s", line)
            continue

        name = m.group(1)
        url = m.group(2)
        label = m.group(3)

        if name in remotes:
            remote = remotes[name]
        else:
            remote = GitRemote(name)
            remotes[name] = remote

        if label == "fetch":
            remote.fetch = url
        elif label == "push":
            remote.push = url
        else:
            log.warning("Ignoring invalid git remote output line: %s", line)

    log.debug("Found %d remotes of %s: %s", len(remotes), path, remotes)
    
    return remotes