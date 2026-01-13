import logging
import os
import queue
import threading
import typer
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional
from .exceptions import GrmError
from .git import GitRepo
from .utils import max_threads


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


FIND_TIMEOUT = 300.0
WORKER_TIMEOUT = 60.0

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

    elif job.depth < options.max_depth:
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
            break

        if state.aborted:
            log.debug("Worker %d aborting job: %s", worker_id, job)
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
    max_depth: int = 1,
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

    num_threads = max_threads(8 if options.matcher.requires_git() else 4)
    log.info("Searching for repositories in %s (using %d threads)",
             path.absolute(), num_threads)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        fs = (executor.submit(_find_worker, options, state)
              for _ in range(num_threads))
        
        try:
            done_fs = wait(fs, timeout=FIND_TIMEOUT).done
        except KeyboardInterrupt:
            state.aborted = True
            for f in fs:
                f.cancel()
            executor.shutdown()
            raise

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
        log.info("Found %d %s from %d %s", match_count, _matches, found_count, _repositories)
    else:
        _repositories = "repository" if match_count == 1 else "repositories"
        log.info("Found %d %s", match_count, _repositories)

    return results


@app.command("find", help="")
def cmd_find():
    pass