import logging
import re
from collections.abc import Collection
from dataclasses import dataclass
from gs.utils import run
from pathlib import Path
from typing import Optional


@dataclass
class GitRemote:
    name: str
    fetch: Optional[str] = None
    push: Optional[str] = None


PATTERN = re.compile(r"^(\S+)\s+(\S+)\s+\((\S+))")

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

    return remotes