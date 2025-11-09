import logging
import re
from ..exceptions import CommandError
from ..utils import run
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BRANCH_FORMAT = "%(HEAD)%(refname:short)...%(upstream:short) %(upstream:track)"
PATTERN_AHEAD = re.compile(r"ahead (\d+)")
PATTERN_BEHIND = re.compile(r"behind (\d+)")

log = logging.getLogger(__name__)

@dataclass
class GitBranch:
    name: str
    is_head: bool = True
    upstream: Optional[str] = None
    ahead: int = -1
    behind: int = -1

    @property
    def track(self) -> str:
        s = ""
        if self.ahead > 0:
            s += f"+{self.ahead}"
        if self.behind > 0:
            if s:
                s += " "
            s += f"-{self.behind}"
        return s


def parse_branch(raw: str) -> GitBranch:
    s = raw

    if s[0] == "*":
        is_head = True
        s = s.removeprefix("*")
    elif s[0] == " ":
        is_head = False
        s = s.removeprefix(" ")
    else:
        raise CommandError("Failed to parse git branch. output="+raw)


    upstream_start = s.find("...")
    if upstream_start >= 0:
        name = s[:upstream_start]
        upstream_end = s.find(" ", upstream_start+3)
        upstream = s[upstream_start+3:upstream_end]
        ahead = 0
        behind = 0

        track_start = s.find("[", upstream_end+1)
        if track_start >= 0:
            track = s[track_start+1:]
            m_ahead = re.match(PATTERN_AHEAD, track)
            if m_ahead:
                ahead = int(m_ahead.group(1))
            m_behind = re.match(PATTERN_BEHIND, track)
            if m_behind:
                behind = int(m_behind.group(1))
    else:
        name = s.rstrip()
        upstream = None
        ahead = -1
        behind = -1

    if not name:
        raise CommandError("Failed to parse git branch. output="+raw)

    return GitBranch(name, is_head, upstream, ahead, behind)


def list_branches(path: Path) -> list[GitBranch]:
    proc = run(("git", "branch", "--format", BRANCH_FORMAT), path)

    if not proc.stdout:
        return []

    results = (parse_branch(line) for line in proc.stdout.splitlines() if line)
    return list(r for r in results if r)
