import logging
import typer
from .context import console_out
from .find import (
    find_repos,
    SEARCH_PATH,
    SEARCH_DEPTH,
    QUERY_NAME,
    QUERY_REMOTE
)
from pathlib import Path
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("status", help="Show status of repositories")
def cmd_status(
    path: Annotated[Path, typer.Argument(
        envvar=SEARCH_PATH.envvar,
        help=SEARCH_PATH.help,
        show_default="Current working directory",
        default_factory=Path.cwd,
    )],
    depth: Annotated[int, typer.Option(
        *SEARCH_DEPTH.options,
        envvar=SEARCH_DEPTH.envvar,
        help=SEARCH_DEPTH.help,
    )] = 1,
    query_name: Annotated[Optional[str], typer.Option(
        *QUERY_NAME.options,
        help=QUERY_NAME.help,
    )] = None,
    query_remote: Annotated[Optional[str], typer.Option(
        *QUERY_REMOTE.options,
        help=QUERY_REMOTE.help,
    )] = None,
):
    _path = path.expanduser().resolve()
    repos = find_repos(
        _path,
        depth,
        status=True,
        query_name=query_name,
        query_remote=query_remote,
    )
    repos.sort(key=lambda repo: str(repo.path))

    table = Table(
        box=None,
        pad_edge=False,
        expand=True,
        header_style="bold underline"
    )
    table.add_column("#", justify="right")
    table.add_column("Name", style="cyan bold")
    table.add_column("Branch")
    table.add_column("Status")

    for i, repo in enumerate(repos):
        status = repo.status

        branch = status.branch.replace("...", " -> ", 1)
        branch_text = Text(branch)

        track_start = branch.find("[")
        if track_start >= 0:
            branch_text.stylize("yellow", start=track_start)

        status_texts: list[Text] = []
        if status.staged > 0:
            status_texts.append(
                Text(f"{status.staged} staged", style="green")
            )
        if status.not_staged > 0:
            status_texts.append(
                Text(f"{status.not_staged} not staged", style="red")
            )
        if status.untracked > 0:
            status_texts.append(
                Text(f"{status.untracked} untracked", style="red")
            )
        status_text = Text(", ").join(status_texts)

        table.add_row(
            str(i+1),
            repo.name,
            branch_text,
            status_text
        )
    
    console_out.print(table)