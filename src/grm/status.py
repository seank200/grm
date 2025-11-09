import logging
import typer
from .context import console_out
from .find import (
    find_repos,
    RepoFilter,
    RepoJob,
    SEARCH_PATH,
    SEARCH_DEPTH,
    FILTER_NAME,
    FILTER_REMOTE,
    FILTER_DIRTY,
)
from .git import GitRepo
from pathlib import Path
from rich.table import Table
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


def render_status(repos: list[GitRepo], render_root: Path) -> Table:
    table = Table(
        title="Repository Status",
        box=None,
        pad_edge=True,
        header_style="bold underline",
    )
    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Branch")
    table.add_column("Status")

    for i, repo in enumerate(repos):
        row_num = str(i+1)
        repo_name = repo.render_path(render_root)
        repo_branch = repo.status.render_branch()
        repo_status = repo.status.render_changes()
        table.add_row(row_num, repo_name, repo_branch, repo_status)

    return table


@app.command("status", help="Show working tree status of repositories")
def cmd_status(
    search_path: Annotated[Path, typer.Argument(
        envvar=SEARCH_PATH.envvar,
        default_factory=Path.cwd,
        show_default="Current working directory",
        help=SEARCH_PATH.help
    )],
    search_depth: Annotated[int, typer.Option(
        *SEARCH_DEPTH.options,
        envvar=SEARCH_DEPTH.envvar,
        help=SEARCH_DEPTH.help,
    )] = 1,
    filter_name: Annotated[Optional[str], typer.Option(
        *FILTER_NAME.options,
        help=FILTER_NAME.help,
    )] = None,
    filter_remote: Annotated[Optional[str], typer.Option(
        *FILTER_REMOTE.options,
        help=FILTER_REMOTE.help,
    )] = None,
    filter_dirty: Annotated[Optional[bool], typer.Option(
        *FILTER_DIRTY.options,
        help=FILTER_DIRTY.help,
    )] = None,
):
    _search_path = search_path.expanduser().resolve()
    repos = find_repos(
        _search_path,
        search_depth,
        filter=RepoFilter(
            name=filter_name,
            remote=filter_remote,
            dirty=filter_dirty,
        ),
        job=RepoJob(status=True)
    )
    repos.sort(key=lambda r: str(r.path))

    console_out.print(render_status(repos, _search_path))