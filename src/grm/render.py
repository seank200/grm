from datetime import datetime, timedelta
from rich.text import Text
from typing import Union
from .config import get_config
from .git import GitRepo


CURRENT_YEAR = datetime.now().year
DATE_THRESHOLD = timedelta(days=180)


class Renderer:
    def __init__(
        self,
        repo: GitRepo,
    ):
        self.repo = repo
        
        config = get_config()
        self.base_path = config.find_path

    def name(self, status_color: bool = False) -> Union[str, Text]:
        if not status_color:
            return self.repo.name
        
        status = self.repo.status()

        if status.unmerged > 0 or (status.operation is not None) or (status.ahead > 0 and status.behind > 0):
            style = "yellow"
        elif status.work_tree > 0:
            style = "red"
        elif status.index > 0:
            style = "green"
        elif status.ahead > 0 or status.behind > 0:
            style = "cyan"
        else:
            style = ""

        return Text(self.repo.name, style=style)


    def status(self, color: bool = True) -> Union[str, Text]:
        status = self.repo.status().concise()

        if not color:
            return status
        
        text = Text(status)

        if status[0] != "-":
            text.stylize("green", 0, 1)

        if status[1] != "-":
            text.stylize("red", 1, 2)

        if status[2] != "-":
            text.stylize("red", 2, 3)

        if status[3] != "-":
            text.stylize("cyan" if status[4] == "-" else "yellow", 3, 4)

        if status[4] != "-":
            text.stylize("cyan" if status[3] == "-" else "yellow", 4, 5)

        if status[5] != "-":
            text.stylize("yellow", 5, 6)

        return text
    
    def head(self) -> Union[str, Text]:
        status = self.repo.status()
        head = status.head

        if head.branch is not None:
            return head.branch.name
        
        if head.commit is not None:
            return Text(
                head.commit.commit_hash[:8],
                style="red" if status.operation is None else "yellow",
            )
        
        return "-"
    
    def last_modified_date(self) -> Union[str, Text]:
        """Returns the author date of HEAD, if HEAD is pointing to a commit"""
        status = self.repo.status()
        head = status.head

        if head.commit is None:
            return "-"
        
        author_date = head.commit.author_date

        if author_date.year != CURRENT_YEAR:
            return author_date.strftime("%b %d  %Y")
        
        return author_date.strftime("%b %d %H:%M")
    
    def upstream_branch(self) -> Union[str, Text]:
        head = self.repo.head()

        if head.branch and head.branch.upstream:
            return head.branch.upstream
        
        return "-"
    
    def operation(self, color: bool = True) -> Union[str, Text]:
        status = self.repo.status()

        if status.operation is None:
            return "-"
        
        return Text(f"{status.operation.value}~{status.unmerged}",
                    style="yellow" if color else "")