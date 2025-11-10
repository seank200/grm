import logging
import re
from dataclasses import dataclass
from grm.utils import run
from pathlib import Path
from rich.text import Text
from typing import Optional
from urllib.parse import urlparse


@dataclass
class GitRemote:
    name: str
    fetch: Optional[str] = None
    push: Optional[str] = None
    
    def render(
        self,
        *,
        short: bool = False,
        show_name: bool = True,
        local_name: Optional[str] = None,
    ):
        if not self.fetch:
            return Text("!", style="red")
        
        parts = urlparse(self.fetch).path.rsplit("/", 1)
        remote_repo = parts[-1].removesuffix(".git")
        if local_name:
            style = "blue" if local_name == remote_repo else "bold red"
        else:
            style = "blue"
        text = Text()
        if short:
            owner = parts[0].removeprefix("/") if len(parts) > 1 else ""
            if owner:
                text.append(owner + "/", style="blue")
            text.append(remote_repo, style=style)
        else:
            text.append(self.fetch, style="blue")
            start = self.fetch.rfind("/")
            end = self.fetch.rfind(".git")
            if start >= 0 and end >= 0:
                text.stylize(style, start+1, end)
        if show_name:
            text.append(f" ({self.name})")
        return text


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