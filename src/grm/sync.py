import logging
import typer
from .context import console_out, console_err, options
from .exceptions import CommandError
from .fetch import worker_fetch, FetchContext, FetchJob, FetchResult
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
from .utils import pl, num_workers, render_result
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeRemainingColumn
from rich.table import Table
from typing import Annotated, Optional


@dataclass
class SyncContext(FetchContext):
    pass


@dataclass
class SyncOptions(FetchJob):
    push: bool = False


@dataclass
class SyncResult(FetchResult):
    merge_succes: Optional[bool] = None
    push_success: Optional[bool] = None


class SyncProgress(Progress):
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


def worker_sync(ctx: SyncContext, repo: GitRepo, opts: SyncOptions) -> SyncResult:
    fetch_result = worker_fetch(ctx, opts)

    if not fetch_result.success:
        return SyncResult(repo, False)
    
    branch = repo.status.parsed_branch
    if branch is None:
        return SyncResult(repo, True)
    
    if branch.upstream is None:
        log.warning(
            "Not syncing %s. Branch '%s' has no remote-tracking branch.",
            repo.name,
            branch.name
        )
        return SyncResult(repo, True)

    if branch.ahead > 0 and branch.behind > 0:
        log.error(
            "Failed to sync '%s' (%s -> %s, ahead %d, behind %d). " \
                + "Remote tracking branch has diverged from local history",
            repo.name,
            branch.name,
            branch.upstream,
            branch.ahead,
            branch.behind
        )
        return SyncResult(repo, True, False, False)

    if branch.ahead > 0 and opts.push:
        try:
            repo.push()
            push_success = True
        except CommandError as err:
            log.error(
                "Failed to push %s (%s -> %s). %s",
                repo.name,
                branch.name,
                branch.upstream,
                err,
            )
            push_success = False
        return SyncResult(repo, True, None, push_success)

    if branch.behind > 0:
        try:
            repo.merge_ff(branch.upstream)
            merge_success = True
        except CommandError as err:
            log.error(
                "Failed to merge %s (%s -> %s). %s",
                repo.name,
                branch.name,
                branch.upstream,
                err,
            )
            merge_success = False
        return SyncResult(repo, True, merge_success, None)
    
    return SyncResult(repo, True)


def sync_repos(
    repos: list[GitRepo],
    *,
    sync_all: bool = False,
    push: bool = False,
) -> list[SyncResult]:
    _repos = (r for r in repos if r.remotes)
    with SyncProgress() as progress:
        task = progress.add_task("Syncing repositories", total=None)
        with ThreadPoolExecutor(max_workers=num_workers()) as executor:
            ctx = SyncContext(executor, progress, task)
            fs = tuple(
                executor.submit(
                    worker_sync,
                    ctx,
                    repo,
                    SyncOptions(repo, all=sync_all, push=push)
                )
                for repo in _repos
            )
            progress.update(task, total=len(fs))

            try:
                done_fs = wait(fs, timeout=120.0).done
            except KeyboardInterrupt:
                executor.shutdown(cancel_futures=True)
                raise

    return [f.result() for f in done_fs]


def render_sync_results(results: list[SyncResult], render_root: Path):
    table = Table(
        title=f"Sync {pl(results, 'result')}",
        box=None,
        pad_edge=True,
        header_style="bold underline",
    )
    table.add_column("#", justify="right")
    table.add_column("Repository")
    table.add_column("Fetch")
    table.add_column("Merge")
    table.add_column("Push")
    table.add_column("Branch")

    for i, r in enumerate(results):
        table.add_row(
            str(i+1),
            r.repo.render_path(render_root),
            render_result(r.success),
            render_result(r.merge_succes),
            render_result(r.push_success),
            r.repo.status.render_branch(),
        )

    return table


@app.command("sync", help="Push to and pull from remote repositories")
def cmd_sync(
    search_path: Annotated[Path, typer.Option(
        *SEARCH_PATH.options,
        envvar=SEARCH_PATH.envvar,
        default_factory=Path.cwd,
        show_default="Current working directory",
        help=SEARCH_PATH.help
    )],
    push: Annotated[bool, typer.Option(
        help="Push local changes after fetch"
    )] = False,
    sync_all: Annotated[bool, typer.Option(
        "--all",
        "-a",
        help="Sync all local branches"
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
        job=RepoJob(remote=True)
    )
    results = sync_repos(repos, sync_all=sync_all, push=push)
    results.sort(key=lambda r: str(r.repo.path))
    console_out.print(render_sync_results(results, _search_path))