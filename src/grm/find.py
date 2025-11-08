import logging
import os
import queue
import threading
import typer
from .context import console_out, console_err
from .exceptions import SubprocessError
from .git import GitRepo
from .utils import OptionDef, pl
from concurrent.futures import Future, ThreadPoolExecutor, wait
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    MofNCompleteColumn,
    TaskID
)
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


@dataclass
class FindJob:
    path: Path
    depth: int


@dataclass
class FindContext:
    progress: Progress
    task: TaskID
    git_remote: bool
    git_status: bool
    query_name: Optional[str]
    query_remote: Optional[str]
    jobs: queue.Queue[FindJob] = field(default_factory=queue.Queue)
    running: bool = True
    _total: int = 1
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def put_job(self, job: FindJob):
        self.jobs.put(job)

    def get_job(self, timeout: Optional[float]) -> Optional[FindJob]:
        try:
            return self.jobs.get(block=timeout is not None, timeout=timeout)
        except queue.Empty:
            return None
        
    def add_total(self, amount: int):
        with self._lock:
            self._total += amount
        self.progress.update(self.task, total=self._total)
    
    def advance(self, amount: float):
        self.progress.advance(self.task, amount)


class FindOutput(Enum):
    TABLE = "table"
    NAME = "name"
    PATH = "path"
    REMOTE = "remote"


SEARCH_PATH = OptionDef(
    "--path",
    "-p",
    envvar="SEARCH_PATH",
    help="Directory to search"
)
SEARCH_DEPTH = OptionDef(
    "--depth",
    "-d",
    envvar="SEARCH_DEPTH",
    help="Maximum search depth from the root path"
)
QUERY_NAME = OptionDef(
    "--name",
    "-n",
    help="Filter repositories by name"
)
QUERY_REMOTE = OptionDef(
    "--remote",
    "-r",
    help="Filter repositories by remote url"
)
OUTPUT = OptionDef(
    "--output",
    "-o",
    help="Output format"
)
app = typer.Typer()
log = logging.getLogger(__name__)


def max_workers() -> int:
    cpu_count = os.cpu_count()
    if cpu_count is None:
        cpu_count = 1

    return min(cpu_count, 4)


def _worker_job(ctx: FindContext, job: FindJob) -> Optional[GitRepo]:
    """Check if current directory is a git repository and add new jobs
    for subdirectories (if `job.depth` > 1)

    Returns:
        Return a `GitRepo` if the current directory is a matching git
        repository, or None if it is not a repository, or if it does not
        match the given search conditions.
    """

    p = job.path
    d = job.depth

    if (p / ".git").is_dir():
        repo = GitRepo(p)

        # Filter by repository name
        if ctx.query_name:
            if ctx.query_name not in repo.name:
                return None
            
        # Filter by repository remote url
        if ctx.running and ctx.query_remote:
            match = False
            for r in repo.remotes.values():
                if r.fetch and ctx.query_remote in r.fetch:
                    match = True
                    break
            if not match:
                return None

        # Pre-run git commands while we are still multi-threaded
        try:
            if ctx.running and ctx.git_remote and not ctx.query_remote:
                repo.remotes
            if ctx.running and ctx.git_status:
                repo.status
        except SubprocessError as error:
            log.error(
                "Failed to inspect [cyan]%s[/cyan]. %s",
                repo.name,
                error,
                extra={"markup": True},
            )
            return None

        return repo

    # Depth is 0. No need to dive in deeper
    if d == 0:
        return None

    new_jobs = 0
    for child in p.iterdir():
        if not ctx.running:
            break
        if child.is_dir():
            ctx.put_job(FindJob(child, d-1))
            new_jobs += 1
    if new_jobs > 0:
        ctx.add_total(new_jobs)

    return None


def _worker_find_repos(ctx: FindContext) -> list[GitRepo]:
    results: list[GitRepo] = []
    visited = 0
    job = ctx.get_job(0.5)
    while job and ctx.running:
        ctx.advance(1)
        visited += 1

        try:
            repo = _worker_job(ctx, job)
            if repo:
                results.append(repo)
        except PermissionError:
            log.error("No permission to search path: %s", job.path)
        except FileNotFoundError:
            log.error("Not searching non-existent path: %s", job.path)
        except NotADirectoryError:
            log.error("Not searching invalid path: %s", job.path)
        except OSError:
            log.error("Failed to search path: %s", job.path)
            raise

        if ctx.running:
            job = ctx.get_job(0.3)

    log.debug("Worker visited %d, and found %d", visited, len(results))

    return results


def find_repos(
    path: Path,
    depth: int = 1,
    *,
    remotes: bool = False,
    status: bool = False,
    query_name: Optional[str] = None,
    query_remote: Optional[str] = None,
) -> list[GitRepo]:
    results: list[GitRepo] = []

    if not path.exists() or not path.is_dir():
        return results

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        MofNCompleteColumn(),
        console=console_err,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Searching directories in {path}")
        num_workers = max_workers()

        with ThreadPoolExecutor(num_workers) as executor:
            ctx = FindContext(
                progress,
                task,
                git_remote=remotes,
                git_status=status,
                query_name=query_name,
                query_remote=query_remote,
            )
            ctx.put_job(FindJob(path, depth))

            done_fs: set[Future[list[GitRepo]]] = set()
            while ctx.jobs.qsize() != 0:
                log.debug("Starting %d workers", num_workers)

                fs = [
                    executor.submit(_worker_find_repos, ctx)
                    for _ in range(num_workers)
                ]

                try:
                    done_fs.update(wait(fs, timeout=30.0).done)
                except KeyboardInterrupt:
                    ctx.running = False
                    executor.shutdown(cancel_futures=True)
                    raise

            repos = [repo for f in done_fs for repo in f.result()]

            log.info(
                "Found %d %s in %s",
                len(repos),
                pl(repos, "repository"),
                path
            )

            return repos


@app.command("find", help="Recursively search for git repositories")
def cmd_find(
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
    output: Annotated[FindOutput, typer.Option(
        *OUTPUT.options,
        help=OUTPUT.help
    )] = FindOutput.TABLE,
):
    _path = path.expanduser().resolve()
    repos = find_repos(
        _path,
        depth,
        remotes=True,
        query_name=query_name,
        query_remote=query_remote,
    )

    repos.sort(key=lambda r: str(r.path))

    if output == FindOutput.NAME:
        for repo in repos:
            console_out.print(repo.name)
        return
    
    if output == FindOutput.PATH:
        for repo in repos:
            console_out.print(repo.path.relative_to(_path))
        return
    
    if output == FindOutput.REMOTE:
        for repo in repos:
            if repo.remotes:
                console_out.print(
                    *[r.fetch for r in repo.remotes.values()],
                    sep="\n"
                )
        return

    table = Table(
        box=None,
        pad_edge=False,
        expand=True,
        header_style="bold underline"
    )
    table.add_column("#", justify="right")
    table.add_column("Name", style="cyan bold")
    table.add_column("Local")
    table.add_column("Remote")

    for i, repo in enumerate(repos):
        local_path = path.joinpath(repo.path.relative_to(_path))

        remotes: list[Text] = []
        for remote in repo.remotes.values():
            # Parse remote owner and repo name
            fetch_path = remote.fetch_path
            if not fetch_path:
                continue
            parts = fetch_path.rsplit("/", 1)

            if len(parts) == 1:
                remote_owner = ""
                remote_repo_name = parts[0].removesuffix(".git")
            else:
                remote_owner = parts[0].removeprefix("/")
                remote_repo_name = parts[1].removesuffix(".git")

            remote_text = Text(
                remote_owner if remote_owner else remote_repo_name
            )

            # Show name only if it is different from its local name
            if repo.name != remote_repo_name:
                remote_text.append(f"/{remote_repo_name}", style="yellow")

            remotes.append(remote_text)

        table.add_row(
            str(i+1),
            repo.name,
            str(local_path),
            Text("\n").join(remotes)
        )

    console_out.print(table)