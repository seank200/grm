import logging
import re
from .branch import GitBranch, parse_branch
from dataclasses import dataclass
from grm.exceptions import CommandError
from grm.utils import run
from pathlib import Path
from rich.text import Text
from typing import Optional


NO_COMMITS = "No commits yet"
DETACHED = "HEAD (no branch)"
UNTRACKED = "?"
UNMODIFIED = " "
PATTERN_AHEAD = re.compile(r"ahead (\d+)")
PATTERN_BEHIND = re.compile(r"behind (\d+)")
log = logging.getLogger(__name__)


@dataclass
class GitStatus:
    branch: str
    not_staged: int
    staged: int
    untracked: int

    _parsed_branch: Optional[GitBranch] = None

    def is_dirty(self) -> bool:
        if self.not_staged + self.staged + self.untracked > 0:
            return True

        branch = self.parsed_branch
        if branch:
            if branch.ahead + branch.behind > 0:
                return True

        return False

    def is_detached(self):
        return self.branch.startswith(DETACHED)

    def no_commits(self):
        return self.branch.startswith(NO_COMMITS)
    
    def render_branch(self) -> Text:
        if self.is_detached():
            return Text("~", style="red")
        if self.no_commits():
            return Text("(NO COMMITS)", style="red")

        branch = self.branch.replace("...", " -> ")
        remote_start = branch.find("-> ")
        if remote_start >= 0:
            text = Text(branch)
            track_start = branch.find("[", remote_start+3)
            if track_start >= 0:
                text.stylize("red", start=0, end=remote_start)
                text.stylize("red", start=track_start)
            else:
                text.stylize("green", start=0, end=remote_start)
        else:
            text = Text(branch, style="green")

        return text

    
    def render_changes(self) -> Text:
        text = Text()
        if self.staged > 0:
            text.append(str(self.staged), style="bold green")
            text.append(" staged")
        if self.not_staged > 0:
            if text:
                text.append(", ")
            text.append(str(self.not_staged), style="bold red")
            text.append(" not staged")
        if self.untracked > 0:
            if text:
                text.append(", ")
            text.append(str(self.untracked), style="bold red")
            text.append(" untracked")
        return text


    @property
    def parsed_branch(self) -> Optional[GitBranch]:
        """Parse branch information from git porcelain output

        Args:
            line (str): git-status branch output line

        Output sample:
        - `## No commits yet on main`
        - `## HEAD (no branch)`
        - `## main...origin/main [ahead 1, behind 2]`
        """
        if self.no_commits() or self.is_detached():
            return None
        
        if self._parsed_branch is None:
            self._parsed_branch = parse_branch("*" + self.branch)

        return self._parsed_branch


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

    status = GitStatus(branch, not_staged, staged, untracked)
    log.debug("Parsed status of '%s': %s", path.name, status)
    return status
