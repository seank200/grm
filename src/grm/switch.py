import logging
import typer
from .exceptions import SubprocessError, CommandError
from .context import console_out, console_err, options
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
from .status import render_status
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeRemainingColumn
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


class SwitchProgress(Progress):
    def __init__(self):
        super().__init__(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console_err,
            transient=not options.debug,
        )


@app.command("switch", help="Switch repositories to target ref")
def cmd_switch(
    refname: Annotated[str, typer.Argument(
        help="Target ref to switch to"
    )],
    search_path: Annotated[Path, typer.Option(
        *SEARCH_PATH.options,
        envvar=SEARCH_PATH.envvar,
        default_factory=Path.cwd,
        show_default="Current working directory",
        help=SEARCH_PATH.help
    )],
    detach: Annotated[bool, typer.Option(
        "--detach",
        help="Allow detached-head state when switching",
    )] = False,
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

    with SwitchProgress() as progress:
        task = progress.add_task("Switching repositories", total=len(repos))
        for repo in repos:
            status = repo.status
            if status.not_staged + status.staged > 0:
                log.warning("Not switching '%s'. Working tree contains changes", repo.name)
            try:
                repo.switch(refname, detach=detach)
            except SubprocessError:
                log.error("Failed to switch '%s' to '%s'.", repo.name, refname)
            except CommandError as e:
                log.error("Failed to switch '%s' to '%s'. %s", repo.name, refname, e)
            finally:
                progress.advance(task, 1)

    console_out.print(render_status(repos, _search_path))