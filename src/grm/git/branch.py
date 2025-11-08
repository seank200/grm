import re
from dataclasses import dataclass
from typing import Optional


PATTERN_AHEAD = re.compile(r"ahead (\d+)")
PATTERN_BEHIND = re.compile(r"behind (\d+)")


@dataclass
class GitBranch:
    name: str
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
