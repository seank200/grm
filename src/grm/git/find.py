import concurrent.futures
import logging
import os
import threading
import pygit2
import queue

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from grm.exceptions import GrmException, ArgValueError
from pathlib import Path, PurePath


log = logging.getLogger(__name__)


@dataclass
class FindJob:
    path: str
    depth: int


@dataclass
class FindState:
    # options
    depth: int
    name: str
    remote_url: str

    # state
    jobs: queue.Queue[FindJob | None]
    results: queue.SimpleQueue[pygit2.Repository]
    aborted: bool = False


class Matcher:
    def __init__(self, *, name: str, remote_url: str):
        self.name = name.lower()
        self.remote_url = remote_url.lower()

    def __call__(self, repo: pygit2.Repository):
        return self.matches_name(repo) and self.matches_remote_url(repo)

    def matches_name(self, repo: pygit2.Repository) -> bool:
        if not self.name:
            return True

        return self.name in PurePath(repo.workdir).name.lower()

    def matches_remote_url(self, repo: pygit2.Repository) -> bool:
        if not self.remote_url:
            return True

        for remote in repo.remotes:
            if remote.url and self.remote_url in remote.url.lower():
                return True

        return False


def find_repos(
    path: Path, depth: int = 0, *, name: str = "", remote_url: str = ""
) -> list[pygit2.Repository]:
    """
    Recursively search for repositories within a directory

    :param path: Search path (a directory)
    :type path: Path
    :param depth: Maximum search depth (0 for no limit)
    :type depth: int
    :param name: Local repository name filter (optional)
    :type name: str
    :param remote_url: Remote repository URL filter (optional)
    :type remote_url: str

    :return: List of found repositories within the search path
    :rtype: list[Repository]
    """

    log.info("Searching in '%s'...", path)

    if not path.is_dir():
        raise ArgValueError(f"Search path is not a directory: '{path}'")

    state = FindState(
        depth=depth,
        name=name,
        remote_url=remote_url,
        jobs=queue.Queue(),
        results=queue.SimpleQueue(),
    )
    state.jobs.put(FindJob(str(path), 0))

    n_workers = min(4, os.cpu_count() or 2)
    with ThreadPoolExecutor(max_workers=n_workers) as exec:
        fs = tuple(exec.submit(_find_worker, state) for _ in range(n_workers))

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            log.warning("Aborting")
            state.aborted = True
            raise

        for _ in range(n_workers):
            state.jobs.put(None)

        try:
            waited_fs = concurrent.futures.wait(fs, timeout=10.0)
        except KeyboardInterrupt:
            log.debug("Aborting cleanup")
            state.aborted = True
            raise

        if waited_fs.not_done:
            log.warning("Not waiting for blocked worker threads")

        final_worker_exception = None
        for f in waited_fs.done:
            try:
                f.result()
            except GrmException as e:
                log.error("Search failed. %s", e, exc_info=True)
            except Exception as e:
                log.error("Search error. %s", e, exc_info=True)
                final_worker_exception = e

        if final_worker_exception is not None:
            raise final_worker_exception

    n_results = state.results.qsize()

    results = []

    while True:
        try:
            result = state.results.get(False)
        except queue.Empty:
            break

        results.append(result)

    if n_results > 0:
        log.info("%d found.", n_results)
    else:
        log.warning("Nothing found.")

    return results


def _find_worker(state: FindState):
    matcher = Matcher(name=state.name, remote_url=state.remote_url)

    while True:
        try:
            job = state.jobs.get(timeout=60.0)
        except queue.Empty:
            log.warning("WARNING: No job for worker %d", threading.get_native_id())
            break

        if job is None:
            log.debug("worker stop")
            state.jobs.task_done()
            break

        if state.aborted:
            log.debug("worker abort")
            state.jobs.task_done()
            break

        try:
            _find_job(job, matcher, state)
        except PermissionError:
            log.warning("No permission to search %s", job.path)
        except TimeoutError:
            log.warning("Directory read timeout on %s", job.path)
        except FileNotFoundError:
            log.debug("Path not found: %s", job.path)
        except NotADirectoryError:
            log.debug("Invalid path: %s", job.path)
        except OSError as e:
            log.error("Failed to search '%s'. %s", job.path, e)
        finally:
            state.jobs.task_done()

        if state.aborted:
            log.debug("worker abort")
            break


def _find_job(job: FindJob, matcher: Matcher, state: FindState):
    path = Path(job.path)

    if (path / ".git").is_dir():
        repo = pygit2.Repository(path)

        if matcher(repo):
            state.results.put(repo)

        return

    if state.depth > 0 and job.depth >= state.depth:
        return

    with os.scandir(job.path) as it:
        for entry in it:
            if entry.is_dir(follow_symlinks=False):
                state.jobs.put_nowait(FindJob(entry.path, job.depth + 1))
