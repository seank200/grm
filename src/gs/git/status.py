import re
from .branch import GitBranch
from dataclasses import dataclass
from gs.exceptions import CommandError
from gs.utils import run
from pathlib import Path
from typing import Optional


NO_COMMITS = "## No commits yet "
DETACHED = "## HEAD (no branch)"
UNTRACKED = "?"
UNMODIFIED = " "

PATTERN_AHEAD = re.compile(r"ahead (\d+)")
PATTERN_BEHIND = re.compile(r"behind (\d+)")


@dataclass
class GitStatus:
    branch: str
    not_staged: int
    staged: int
    untracked: int

    def parse_branch(self) -> Optional[GitBranch]:
        """Parse branch information from git porcelain output

        Args:
            line (str): git-status branch output line

        Output sample:
        - `## No commits yet on main`
        - `## HEAD (no branch)`
        - `## main...origin/main [ahead 1, behind 2]`
        """
        l = self.branch.lstrip("## ")

        if l.startswith(NO_COMMITS) or l.startswith(DETACHED):
            return None
        
        i = l.find("...")

        upstream = None
        ahead = -1
        behind = -1

        if i > 0:
            name = l[:i]
            upstream = l[i+3:]
            m_ahead = re.match(PATTERN_AHEAD, l)
            if m_ahead:
                ahead = int(m_ahead.group(1))
            m_behind = re.match(PATTERN_BEHIND, l)
            if m_behind:
                behind = int(m_behind.group(1))
        else:
            name = l

        return GitBranch(name, upstream, ahead, behind)


def show_status(path: Path) -> GitStatus:
    args = "git status --porcelain --branch".split(" ")
    proc = run(args, path)
    if not proc.stdout:
        raise CommandError("git-status returned an empty output")

    lines = proc.stdout.splitlines()
    branch_line: str = lines[0]
    if not branch_line.startswith("## "):
        raise CommandError(f"Invalid git-status branch line: {branch_line}")

    branch = branch_line.lstrip("## ")
    not_staged = 0
    staged = 0
    untracked = 0
    
    for line in lines[1:]:
        x = line[0]
        y = line[1]

        if x == UNTRACKED:
            untracked += 1
        else:
            if x != UNMODIFIED:
                staged += 1
            if y != UNMODIFIED:
                not_staged += 1

    return GitStatus(branch, not_staged, staged, untracked)