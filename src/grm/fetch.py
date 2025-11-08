import logging
import typer
from .exceptions import SubprocessError
from .find import (
    find_repos,
    SEARCH_PATH,
    SEARCH_DEPTH,
    QUERY_NAME,
    QUERY_REMOTE
)
from .git import GitRepo
from .utils import OptionDef, pl
from collections.abc import Collection
from concurrent.futures import wait, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from rich.progress import Progress, TaskID, TextColumn, BarColumn, MofNCompleteColumn, TimeRemainingColumn
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


FETCH_ALL = OptionDef(
    "--all",
    "-a",
    help="Fetch all remotes"
)

FETCH_PRUNE = OptionDef(
    "--prune",
    "-p",
    help="Remove remote refs that no longer exist"
)

MAX_WORKERS = OptionDef(
    "--max-workers",
    "-j",
    help="Maximum number of threads to fetch repositories"
)

DEFAULT_MAX_WORKERS = 3


@dataclass
class FetchJob:
    progress: Progress
    task: TaskID
    repo: GitRepo
    fetch_all: bool
    prune: bool

    def advance(self, amount: float = 1):
        self.progress.advance(self.task, amount)


def _worker_fetch(job: FetchJob) -> bool:
    try:
        log.info("Fetching [cyan]%s[/]", job.repo.name)
        job.repo.fetch()
        job.advance(1)
        return True
    except SubprocessError:
        log.error(
            "Failed to fetch [cyan]%s[/]",
            job.repo.name,
            extra={"markup": True},
        )
    return False


def fetch(
    repos: Collection[GitRepo],
    fetch_all: bool,
    prune: bool,
    max_workers: int = DEFAULT_MAX_WORKERS,
):
    with Progress() as progress:
        task = progress.add_task("Fetching repositories", total=len(repos))
        with ThreadPoolExecutor(max_workers) as executor:
            fs = [
                executor.submit(
                    _worker_fetch,
                    FetchJob(progress, task, repo, fetch_all, prune)
                )
                for repo in repos
            ]

            try:
                done_fs = wait(fs, timeout=300.0).done
            except KeyboardInterrupt:
                executor.shutdown(cancel_futures=True)

    success_count = 0
    for f in done_fs:
        if f.result():
            success_count += 1

    log.info(
        "Fetched [bold green]%d[/] %s",
        success_count,
        pl(success_count, "repository"),
        extra={"markup": True},
    )

    failed_count = len(repos) - success_count
    if failed_count:
        log.error(
            "Failed to fetch [bold red]%d[/] %s",
            failed_count,
            pl(failed_count, "repository")
        )


@app.command("fetch", help="Fetch remote repositories")
def cmd_fetch(
    path: Annotated[Path, typer.Argument(
        envvar=SEARCH_PATH.envvar,
        help=SEARCH_PATH.help,
        show_default="Current working directory",
        default_factory=Path.cwd,
    )],
    fetch_all: Annotated[bool, typer.Option(
        *FETCH_ALL.options,
        help=FETCH_ALL.help,
    )] = False,
    prune: Annotated[bool, typer.Option(
        *FETCH_PRUNE.options,
        help=FETCH_PRUNE.help,
    )] = False,
    max_workers: Annotated[int, typer.Option(
        *MAX_WORKERS.options,
        help=MAX_WORKERS.help,
    )] = DEFAULT_MAX_WORKERS,
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
    fetch(repos, fetch_all, prune, max_workers)