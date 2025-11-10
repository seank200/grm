import logging
import typer
from .exceptions import CommandError
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
from .git import GitRepo, GitBranch
from .utils import num_workers, render_result
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from rich.progress import Progress, TaskID, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeRemainingColumn
from rich.table import Table
from typing import Annotated, Optional


@dataclass
class SwitchContext:
    progress: Progress
    task: TaskID


@dataclass
class SwitchResult:
    success: bool
    repo: GitRepo
    before_branch: Optional[GitBranch]


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


def _worker_switch(ctx: SwitchContext, repo: GitRepo, refname: str, detach: bool):
    before_branch: Optional[GitBranch] = repo.status.parsed_branch

    try:
        repo.switch(refname, detach=detach)
        repo.status
        success = True
    except CommandError:
        success = False
    finally:
        ctx.progress.advance(ctx.task, 1)

    return SwitchResult(success, repo, before_branch)


def switch_repos(
    repos: list[GitRepo],
    refname: str,
    *,
    detach: bool = False,
) -> list[SwitchResult]:

    with SwitchProgress() as progress:
        task = progress.add_task("Switching repositories", total=len(repos))
        ctx = SwitchContext(progress, task)
        with ThreadPoolExecutor(max_workers=num_workers()) as executor:
            fs = (
                executor.submit(_worker_switch, ctx, repo, refname, detach)
                for repo in repos
            )

            try:
                done_fs = wait(fs, timeout=60.0).done
            except KeyboardInterrupt:
                executor.shutdown(cancel_futures=True)
                raise

            return [f.result() for f in done_fs]


def render_switch(results: list[SwitchResult], render_root: Path) -> Table:
    table = Table(
        title="Repository Status",
        box=None,
        pad_edge=True,
        header_style="bold underline",
    )

    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Switch")
    table.add_column("Before")
    table.add_column("After")

    for i, result in enumerate(results):
        table.add_row(
            str(i+1),
            result.repo.render_path(render_root),
            render_result(result.success),
            result.before_branch.name if result.before_branch else "(HEAD)",
            result.repo.status.render_branch(),
        )

    return table


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

    results = switch_repos(repos, refname, detach=detach)
    results.sort(key=lambda r: str(r.repo.path))

    console_out.print(render_switch(results, _search_path))