import logging
import typer
from .context import console_out, console_err, options
from .exceptions import CommandError
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
from .utils import pl, num_workers
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from rich.progress import Progress, TaskID, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


@dataclass
class FetchJob:
    repo: GitRepo
    remote: Optional[str] = None
    all: bool = False
    prune: bool = False


@dataclass
class FetchContext:
    executor: ThreadPoolExecutor
    progress: Progress
    task: TaskID


@dataclass
class FetchResult:
    repo: GitRepo
    success: bool


class FetchProgress(Progress):
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


app = typer.Typer()
log = logging.getLogger(__name__)


def worker_fetch(ctx: FetchContext, job: FetchJob) -> FetchResult:
    try:
        job.repo.fetch(job.remote, all=job.all, prune=job.prune)
        job.repo.status  # Concurrently cache results to speed up rendering
        success = True
    except CommandError as err:
        log.error(
            "Failed to fetch %s%s. %s",
            job.repo.name,
            f" ({job.remote})" if job.remote else "",
            err,
        )
        success = False
    finally:
        ctx.progress.advance(ctx.task, 1)
    return FetchResult(job.repo, success)


def _submit_jobs(
    ctx: FetchContext,
    repos: Iterable[GitRepo],
    remote: Optional[str],
    fetch_all: bool,
    prune: bool,
    filter: Optional[RepoFilter],
):
    if fetch_all:
        return tuple(
            ctx.executor.submit(
                worker_fetch,
                ctx,
                FetchJob(repo, remote.name, all=False, prune=prune)
            )
            for repo in repos
            for remote in repo.remotes.values()
            if filter is None or filter.matches_remote(remote)
        )

    return tuple(
        ctx.executor.submit(
            worker_fetch,
            ctx,
            FetchJob(repo, remote, all=False, prune=prune)
        )
        for repo in repos
        if not remote or remote in repo.remotes
    )


def fetch_repos(
    repos: list[GitRepo],
    remote: Optional[str] = None,
    *,
    fetch_all: bool = False,
    prune: bool = False,
    filter: Optional[RepoFilter] = None,
) -> list[FetchResult]:
    with FetchProgress() as progress:
        task = progress.add_task("Fetching repositories", total=None)
        with ThreadPoolExecutor(max_workers=num_workers()) as executor:
            ctx = FetchContext(executor, progress, task)
            fs = _submit_jobs(ctx, repos, remote, fetch_all, prune, filter)
            progress.update(task, total=len(fs))

            try:
                done_fs = wait(fs, timeout=120.0).done
            except KeyboardInterrupt:
                executor.shutdown(cancel_futures=True)
                raise

    return [f.result() for f in done_fs]


def _render_results(
    results: list[FetchResult],
    render_root: Optional[Path] = None
) -> Table:
    table = Table(
        title=f"Fetch {pl(results, 'result')}",
        box=None,
        header_style="bold underline",
    )
    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Fetch")
    table.add_column("Branch")

    for i, result in enumerate(results):
        if result.success:
            status = Text("SUCCESS", style="bold green")
            branch = result.repo.status.render_branch()
        else:
            status = Text("ERROR", style="bold red")
            branch = ""

        table.add_row(
            str(i+1),
            result.repo.render_path(render_root),
            status,
            branch,
        )

    return table


@app.command("fetch", help="Fetch from remote repositories")
def cmd_fetch(
    search_path: Annotated[Path, typer.Option(
        *SEARCH_PATH.options,
        envvar=SEARCH_PATH.envvar,
        default_factory=Path.cwd,
        show_default="Current working directory",
        help=SEARCH_PATH.help
    )],
    remote_name: Annotated[Optional[str], typer.Argument(
        help="Name of remote to fetch"
    )] = None,
    fetch_all: Annotated[bool, typer.Option(
        "--all",
        "-a",
        help="Fetch all remotes"
    )] = False,
    prune: Annotated[bool, typer.Option(
        "--prune",
        help="Remove refs that no longer exist in remote"
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
    filter = RepoFilter(
        name=filter_name,
        remote=filter_remote,
        dirty=filter_dirty,
    )
    repos = find_repos(
        _search_path,
        search_depth,
        filter=filter,
        job=RepoJob(remote=True)
    )
    results = fetch_repos(
        repos,
        remote_name,
        fetch_all=fetch_all,
        prune=prune,
        filter=filter
    )
    results.sort(key=lambda r: f"{int(not r.success)}{r.repo.path}")
    console_out.print(_render_results(results, _search_path))