import logging
import os
import queue
import threading
import typer
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from rich import print as rich_print
from rich.text import Text
from rich.table import Table
from typing import Annotated, Optional
from .config import get_config
from .exceptions import GrmError
from .git import GitRepo
from .render import Renderer
from .utils import max_threads


class FindOutput(Enum):
    NAME = "name"


@dataclass
class FindJob:
    path: Path
    depth: int


@dataclass
class FindState:
    jobs: queue.Queue[Optional[FindJob]]
    results: list[GitRepo]
    lock: threading.Lock
    aborted: bool = False


@dataclass
class FindOptions:
    path: Path
    max_depth: int
    matcher: 'Matcher'


CLEANUP_TIMEOUT = 10.0
WORKER_TIMEOUT = 5.0

app = typer.Typer()
log = logging.getLogger(__name__)


class Matcher:
    def __init__(
        self,
        query_name: Optional[str] = None,
        query_remote_name: Optional[str] = None,
        query_remote_url: Optional[str] = None,
        query_clean: Optional[bool] = None,
        case_sensitive: bool = False,
        exact: bool = False,
    ):
        self.query_name = query_name \
            if (not query_name or case_sensitive) \
                else query_name.lower()
        self.query_remote_name = query_remote_name \
            if (not query_remote_name or case_sensitive) \
                else query_remote_name.lower()
        self.query_remote_url = query_remote_url \
            if (not query_remote_url or case_sensitive) \
                else query_remote_url.lower()
        self.query_clean = query_clean
        
        self.case_sensitive = case_sensitive
        self.exact = exact

    def matches_name(self, repo: GitRepo) -> bool:
        if not self.query_name:
            return True

        name = repo.path.name if self.case_sensitive \
            else repo.path.name.lower()

        if self.exact:
            return name == self.query_name
        
        return self.query_name in name
    
    def matches_remote(self, repo: GitRepo) -> bool:
        q_name = self.query_remote_name
        q_url = self.query_remote_url

        if not q_name and not q_url:
            return True
        
        for remote in repo.get_remotes().values():
            if q_name:
                v_name = remote.name if self.case_sensitive \
                    else remote.name.lower()

                if self.exact:
                    if q_name != v_name:
                        continue
                else:
                    if q_name not in v_name:
                        continue

            if q_url:
                v_url = remote.url if self.case_sensitive \
                    else remote.url.lower()
                if self.exact:
                    if q_url != v_url:
                        continue
                else:
                    if q_url not in v_url:
                        continue

            return True
        
        return False
    
    def matches_status(self, repo: GitRepo) -> bool:
        return self.query_clean is None \
            or self.query_clean == repo.is_clean()
        
    def requires_git(self) -> bool:
        return self.query_remote_name is not None \
            or self.query_remote_url is not None \
                or self.query_clean is not None


def _do_job(options: FindOptions, state: FindState, job: FindJob):
    if job.path.joinpath(".git").is_dir():
        repo = GitRepo(job.path)
        is_match = options.matcher.matches_name(repo) \
                and options.matcher.matches_remote(repo) \
                and options.matcher.matches_status(repo)
        if is_match:
            with state.lock:
                state.results.append(repo)

        return True

    elif options.max_depth <= 0 or job.depth < options.max_depth:
        with os.scandir(job.path) as it:
            for entry in it:
                if state.aborted:
                    break

                if entry.is_dir(follow_symlinks=False):
                    state.jobs.put(
                        FindJob(Path(entry.path), job.depth+1),
                        timeout=WORKER_TIMEOUT
                    )

    return False
    

def _find_worker(options: FindOptions, state: FindState):
    worker_id = threading.get_native_id()
    job_count = 0
    found_count = 0

    while True:
        try:
            job = state.jobs.get(timeout=WORKER_TIMEOUT)
        except queue.Empty:
            log.debug("Worker %d timeout after %f seconds",
                        worker_id, WORKER_TIMEOUT)
            raise

        if job is None:
            log.debug("Worker %d terminating (signal from main thread)",
                      worker_id)
            state.jobs.task_done()
            break

        if state.aborted:
            log.debug("Worker %d aborting job: %s", worker_id, job)
            state.jobs.task_done()
            break

        found = False

        try:
            found = _do_job(options, state, job)
        except queue.Full:
            log.debug("Aborting search (job queue full for %f seconds): %s",
                      WORKER_TIMEOUT, job.path)
            state.aborted = True
            raise
        except PermissionError:
            log.error("ERROR: No permission to search '%s'", job.path)
        except FileNotFoundError:
            log.debug("Path not found: %s", job.path)
        except NotADirectoryError:
            log.debug("Invalid path: %s", job.path)
        except OSError as e:
            log.error("ERROR: Failed to search '%s'. %s", e)
        finally:
            job_count += 1
            state.jobs.task_done()

        if found:
            found_count += 1

        if state.aborted:
            log.debug("Worker %d aborted job: %s", worker_id, job)
            break

    log.debug("Worker %d: Visited %d, found %d", worker_id, job_count, found_count)
    return found_count
    

def find_repos(
    path: Path,
    max_depth: int,
    matcher: Optional[Matcher] = None,
) -> list[GitRepo]:
    results: list[GitRepo] = []

    options = FindOptions(path, max_depth, matcher or Matcher())
    state = FindState(
        jobs=queue.Queue(),
        results=results,
        lock=threading.Lock(),
    )
    found_count = 0
    state.jobs.put(FindJob(path, 0))

    num_threads = max_threads(6 if options.matcher.requires_git() else 4)
    log.debug("Searching for repositories in %s", path.absolute())

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        fs = tuple(executor.submit(_find_worker, options, state)
              for _ in range(num_threads))
        
        try:
            state.jobs.join()     # Wait for all jobs to complete
        except KeyboardInterrupt:
            state.aborted = True
            raise

        for _ in range(num_threads):
            state.jobs.put(None)  # Send stop signal to all workers

        try:
            state.jobs.join()     # Wait for all workers to stop
        except KeyboardInterrupt:
            state.aborted = True
            raise

        waited_fs = wait(fs, timeout=CLEANUP_TIMEOUT)  # Wait for all threads
        if len(waited_fs.not_done) > 0:
            log.warning("WARNING: Not waiting for worker threads that took too long to terminate.")

        done_fs = waited_fs.done

        try:
            for f in done_fs:
                found_count += f.result()  # Raise exceptions (if any)
        except queue.Empty:
            raise GrmError("Search failed (filesystem read timeout)")
        except queue.Full:
            raise GrmError("Search failed (job queue is full)")
        
    match_count = len(results)

    if match_count < found_count:
        _matches = "match" if match_count == 1 else "matches"
        _repositories = "repository" if found_count == 1 else "repositories"
        log.debug("Found %d %s from %d %s", match_count, _matches, found_count, _repositories)
    else:
        _repositories = "repository" if match_count == 1 else "repositories"
        log.debug("Found %d %s", match_count, _repositories)

    return results


@app.command("find", help="Search for local repositories")
def cmd_find(
    query_name: Annotated[Optional[str], typer.Argument(
        help="(Search condition) repository name",
    )] = None,
    find_max_depth: Annotated[Optional[int], typer.Option(
        "-d", "--depth",
        help="Repository search depth",
    )] = None,
    query_remote_name: Annotated[Optional[str], typer.Option(
        "-r", "--remote",
        help="(Search condition) Repository remote name (e.g. 'origin')",
    )] = None,
    query_remote_url: Annotated[Optional[str], typer.Option(
        "-u", "--url",
        help="(Search condition) Repository remote url",
    )] = None,
    query_clean: Annotated[Optional[bool], typer.Option(
        "--clean/--dirty",
        help="(Search condition) Whether working tree contains/does not contain uncommitted changes to tracked files",
    )] = None,
    matcher_case_sensitive: Annotated[Optional[bool], typer.Option(
        "-C", "--case-sensitive",
        help="Case sensitive search query",
    )] = None,
    matcher_exact: Annotated[Optional[bool], typer.Option(
        "-e", "--exact", 
        help="Perform an exact match of search query (default: substring match)",
    )] = None,
    sort: Annotated[bool, typer.Option(
        "--sort/--no-sort",
        help="Sort search results",
    )] = True,
    output: Annotated[Optional[FindOutput], typer.Option(
        "-o", "--output",
        help="Output format",
    )] = None
):
    config = get_config()

    if find_max_depth is not None:
        config.find_max_depth = find_max_depth

    if query_remote_name is not None:
        config.query_remote_name = query_remote_name

    if query_remote_url is not None:
        config.query_remote_url = query_remote_url
    
    if query_clean is not None:
        config.query_clean = query_clean

    if matcher_case_sensitive is not None:
        config.matcher_case_sensitive = matcher_case_sensitive
    
    if matcher_exact is not None:
        config.matcher_exact = matcher_exact

    if query_name is not None:
        config.query_name = query_name

    matcher = Matcher(
        query_name=config.query_name,
        query_remote_name=config.query_remote_name,
        query_remote_url=config.query_remote_url,
        query_clean=config.query_clean,
        case_sensitive=config.matcher_case_sensitive,
        exact=config.matcher_exact,
    )
    repos = find_repos(config.find_path, config.find_max_depth, matcher)

    if sort:
        repos.sort(key=lambda repo: str(repo.path))


    for repo in repos:
        if output == FindOutput.NAME:
            print(repo.path.name)
        else:
            print(repo.path)


@app.command("ls", help="List git repositories in current directory")
def cmd_list(
    sort: Annotated[bool, typer.Option(
        "--sort/--no-sort",
        help="Sort output",
    )] = True,
    long: Annotated[bool, typer.Option(
        "-l", "--long",
        help="Display long output",
    )] = False,
    show_legend: Annotated[bool, typer.Option(
        "-g", "--legend",
        help="Display headers and legend on long output"
    )] = False,
):
    repos = find_repos(Path.cwd(), 1)

    if sort:
        repos.sort(key=lambda repo: str(repo.path))

    if not long:
        for repo in repos:
            print(repo.path.name)
        return
    
    with ThreadPoolExecutor(max_workers=max_threads(8)) as executor:
        fs = (executor.submit(lambda repo: repo.status(), repo) for repo in repos)
        try:
            wait(fs, timeout=60.0)
        except KeyboardInterrupt:
            log.warning("Aborting repository status check")
            for f in fs:
                f.cancel()
            raise

    table = Table(
        pad_edge=False,
        box=None,
        show_header=show_legend,
        header_style="underline",
        show_footer=show_legend,
        caption="X: Index, Y: Working Tree, ?: Untracked, A: Ahead, B: Behind" if show_legend else None,
        caption_justify="left",
    )
    table.add_column("X", justify="right")
    table.add_column("Y", justify="right")
    table.add_column("?", justify="right")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("HEAD")
    table.add_column("Upstream")
    table.add_column("Name")
    table.add_column()  # Interactive git operations in progress

    for repo in repos:
        renderer = Renderer(repo)
        status = repo.status()

        table.add_row(
            Text(str(status.index), style="green" if status.index else "dim"),
            Text(str(status.work_tree), style="red" if status.work_tree else "dim"),
            Text(str(status.untracked), style="red" if status.untracked else "dim"),
            renderer.branch_ahead(),
            renderer.branch_behind(),
            renderer.head(),
            renderer.branch_upstream(),
            renderer.name(status=True),
            renderer.in_progress(),
        )

    rich_print(table)