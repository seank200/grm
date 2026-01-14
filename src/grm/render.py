from pathlib import Path
from rich.text import Text
from typing import Optional, Union
from .config import get_config
from .git import GitRepo


class Renderer:
    def __init__(
        self,
        repo: GitRepo,
    ):
        self.repo = repo
        self.base_path = get_config().find_path

    def name(self, status: bool = False) -> Text:
        if status:
            _status = self.repo.status()
            branch = _status.head.branch
            ahead = branch.ahead if branch else -1
            behind = branch.behind if branch else -1

            if _status.in_progress is not None or (ahead > 0 and behind > 0):
                style = "magenta"
            elif _status.work_tree > 0:
                style = "red"
            elif _status.index > 0:
                style = "green"
            elif ahead + behind > 0:
                style = "cyan"
            else:
                style = ""
        else:
            style = ""

        return Text(self.repo.name, style=style)
    
    def path(self, relative_to: Optional[Path] = None) -> str:
        return str(self.repo.path.relative_to(relative_to)) if relative_to \
            else str(self.repo.path)
    
    def head(self, short: bool = True) -> Union[str, Text]:
        status = self.repo.status()
        head = status.head

        if head.branch is None:
            if head.oid:
                return Text(f"{head.oid[:8] if short else head.oid}", style="red" if status.in_progress is None else "magenta")
            else:
                return Text("(no commits)", style="dim")

        return head.branch.name
    
    def branch_upstream(self) -> Union[str, Text]:
        status = self.repo.status()
        head = status.head

        if head.branch is None:
            return Text("-", style="dim")
        
        if head.branch.upstream is None:
            return Text("-", style="dim")
        
        return head.branch.upstream
    
    def branch_ahead(self) -> Union[str, Text]:
        head = self.repo.head()

        if head.branch is None:
            return Text("-", style="dim")
        
        if head.branch.ahead < 0:
            return Text("-", style="dim")

        if head.branch.ahead > 0 and head.branch.behind > 0:
            style = "magenta"
        elif head.branch.ahead > 0:
            style = "cyan"
        else:
            style = "dim"
        
        return Text(str(head.branch.ahead), style=style)

    def branch_behind(self) -> Union[str, Text]:
        head = self.repo.head()

        if head.branch is None:
            return Text("-", style="dim")
        
        if head.branch.behind < 0:
            return Text("-", style="dim")

        if head.branch.ahead > 0 and head.branch.behind > 0:
            style = "magenta"
        elif head.branch.behind > 0:
            style = "cyan"
        else:
            style = "dim"
        
        return Text(str(head.branch.behind), style=style)
    
    def in_progress(self) -> Union[str, Text]:
        status = self.repo.status()

        if status.in_progress is None:
            return ""
        
        return Text(f"{status.in_progress.value}~{status.unmerged}", style="magenta")


def render_repos(repos):
    pass