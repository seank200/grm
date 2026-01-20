import argparse
import concurrent.futures
import logging
import os
import pygit2
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from .config import config
from .exceptions import CommandError
from .options import subparsers, filter_parser, render_parser
from .render import render_repos
from .utils import max_threads


log = logging.getLogger(__name__)

parser = subparsers.add_parser(
    "find",
    parents=[filter_parser, render_parser],
    description="Recursively search for local repositories",
    help="Recursively search for local repositories",
)

parser.add_argument(
    "path",
    type=Path,
    help="repository search path",
)

parser.add_argument(
    "-d", "--depth",
    default=0,
    type=int,
    help="maximum search depth (0 for no recursion limit) [default: 0]"
)


@dataclass
class FindJob:
    path: Path
    depth: int


@dataclass
class FindState:
    jobs: queue.Queue[Optional[Path]]
    results: list[pygit2.Repository]
    lock: threading.Lock
    aborted: bool = False


@dataclass
class FindOptions:
    max_depth: int
    filter: 'RepoFilter'
    hidden: bool


class RepoFilter:
    @staticmethod
    def create(args: argparse.Namespace) -> 'RepoFilter':
        return RepoFilter(
            name=args.name or "",
            remote_url=args.url or "",
            case_sensitive=args.case_sensitive,
            exact=args.exact,
        )

    def __init__(
        self,
        name: str = "",
        remote_url: str = "",
        case_sensitive: bool = False,
        exact: bool = False,
    ):
        if case_sensitive:
            self.name = name
            self.remote_url = remote_url
        else:
            self.name = name.lower()
            self.remote_url = remote_url.lower()

        self.case_sensitive = case_sensitive
        self.exact = exact

    def matches(self, repo: pygit2.Repository) -> bool:
        return self.matches_name(repo) \
            and self.matches_remote_url(repo)

    def matches_name(self, repo: pygit2.Repository) -> bool:
        if not self.name:
            return True

        return self._matches_str(self.name, Path(repo.workdir).name)

    def matches_remote_url(self, repo: pygit2.Repository) -> bool:
        if not self.remote_url:
            return True

        for remote_name in repo.remotes.names():
            url = repo.remotes[remote_name].url

            if self._matches_str(self.remote_url, url):
                return True

        return False

    def _matches_str(self, query: str, value: str) -> bool:
        _value = value if self.case_sensitive else value.lower()

        if self.exact:
            return query == _value

        return query in _value


def _worker_job(job: FindJob, state: FindState, options: FindOptions) -> bool:
    repo_path: str = pygit2.discover_repository(job.path)

    if repo_path:
        repo = pygit2.Repository(repo_path)

        if options.filter.matches(repo):
            with state.lock:
                state.results.append(repo)

        return True

    elif options.max_depth <= 0 or job.depth < options.max_depth:
        with os.scandir(job.path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) \
                        and (options.hidden or not entry.name.startswith(".")):
                    state.jobs.put(FindJob(Path(entry.path), job.depth+1))

    return False


def _worker(state: FindState, options: FindOptions):
    tid = threading.get_native_id()
    visited = 0
    found = 0

    while True:
        if state.aborted:
            log.debug("find: worker %d break: abort signal", tid)
            break

        try:
            job = state.jobs.get(timeout=300.0)
        except queue.Empty:
            log.debug("find: worker %d break: no jobs", tid)
            break

        if job is None:
            state.jobs.task_done()
            break

        if state.aborted:
            log.debug("find: worker %d break: abort signal", tid)
            break

        try:
            is_repo = _worker_job(job, state, options)
            if is_repo:
                found += 1
        except FileNotFoundError:
            log.debug("find: path not found: %s", job.path)
        except NotADirectoryError:
            log.debug("find: invalid path: %s", job.path)
        except PermissionError:
            log.error("find: error: no permission to search '%s'", job.path)
        except TimeoutError:
            log.error("find: error: directory read timeout on '%s'", job.path)
        except OSError as e:
            log.error("find: error: failed to search '%s': %s", job.path, e,
                      exc_info=config.debug)
        finally:
            visited += 1
            state.jobs.task_done()

    log.debug("find: worker %d terminating (visited %d, found %d)",
              tid, visited, found)
    return found


def find_repos(
    path: Path,
    max_depth: int = 0,
    filter: Optional[RepoFilter] = RepoFilter(),
    hidden: bool = False,
    raise_if_not_found: bool = True,
) -> list[pygit2.Repository]:

    options = FindOptions(max_depth, filter, hidden)
    state = FindState(
        jobs=queue.Queue(),
        results=[],
        lock=threading.Lock(),
    )
    state.jobs.put(FindJob(path, 0))

    num_workers = max_threads()
    with ThreadPoolExecutor(max_workers=num_workers) as exec:
        log.info("find: Searching for repositories in '%s'... (%d threads)",
                 path.resolve(), num_workers)

        fs = tuple(exec.submit(_worker, state, options)
                   for _ in range(num_workers))

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            log.warning("find: Aborting")
            state.aborted = True
            raise

        for _ in range(num_workers):
            state.jobs.put(None)

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            state.aborted = True
            raise

        waited_fs = concurrent.futures.wait(fs, timeout=10.0)
        if len(waited_fs.done) < len(waited_fs.not_done):
            log.warning("find: warning: Not waiting for workers that took"
                        " too long to terminate")

        found = 0
        for f in waited_fs.done:
            found += f.result()

    matches = len(state.results)

    if raise_if_not_found and matches == 0:
        raise CommandError(f"No repositories found in '{path.absolute()}'")

    _repositories = "repository" if matches == 1 else "repositories"
    if matches < found:
        log.info(f"find: Found %d {_repositories} (total %d)", matches, found)
    else:
        log.info(f"find: Found %d {_repositories}", found)

    return state.results


def cmd_find(args: argparse.Namespace):
    repos = find_repos(
        args.path,
        max_depth=args.depth,
        filter=RepoFilter.create(args),
        raise_if_not_found=False,
    )

    render_repos(repos, args)
