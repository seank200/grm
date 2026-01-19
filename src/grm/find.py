import argparse
import concurrent.futures
import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from .config import config
from .exceptions import CommandError, OptionError
from .git import GitRepo
from .options import subparsers, filter_parser
from .utils import max_threads


@dataclass
class FindJob:
    path: Path
    depth: int


@dataclass
class FindState:
    jobs: queue.Queue[Optional[Path]]
    results: list[GitRepo]
    lock: threading.Lock
    aborted: bool = False


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

    def matches(self, repo: GitRepo) -> bool:
        return self.matches_name(repo) \
            and self.matches_remote_url(repo)

    def matches_name(self, repo: GitRepo) -> bool:
        if not self.name:
            return True

        return self._matches_str(self.name, repo.name)

    def matches_remote_url(self, repo: GitRepo) -> bool:
        if not self.remote_url:
            return True

        remotes = repo.remotes()
        for url in remotes.values():
            if self._matches_str(self.remote_url, url):
                return True

        return False

    def _matches_str(self, query: str, value: str) -> bool:
        _value = value if self.case_sensitive else value.lower()

        if self.exact:
            return query == _value

        return query in _value


@dataclass
class FindOptions:
    max_depth: int
    filter: RepoFilter
    hidden: bool


log = logging.getLogger(__name__)

parser = subparsers.add_parser(
    "find",
    parents=[filter_parser],
    description="Recursively search for local repositories",
    help="Recursively search for local repositories",
)

parser.add_argument(
    "path",
    type=Path,
    help="directory path to search",
)

parser.add_argument(
    "-d", "--depth",
    default=0,
    type=int,
    help="maximum search depth (0: no limit, default: 0)"
)

OUTPUT_ABSOLUTE = "absolute"
OUTPUT_RELATIVE = "relative"
OUTPUT_RESOLVE = "resolve"
OUTPUT_URL = "url"

parser.add_argument(
    "-o", "--output",
    choices=[OUTPUT_ABSOLUTE, OUTPUT_RELATIVE, OUTPUT_RESOLVE, OUTPUT_URL],
    default="relative",
    help=f"""Output format ('{OUTPUT_ABSOLUTE}': absolute local path,
    '{OUTPUT_RELATIVE}': local path relative to the search directory,
    '{OUTPUT_RESOLVE}': absolute path with symlink resolution,
    '{OUTPUT_URL}': all remote URLs)""",
)


def _worker_job(job: FindJob, state: FindState, options: FindOptions) -> bool:
    if job.path.joinpath(".git").is_dir():
        repo = GitRepo(job.path)

        if options.filter.matches(repo):
            log.debug("Found repository '%s'", repo.name)
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
            log.debug("worker %d break: abort signal from main thread")
            break

        try:
            job = state.jobs.get(timeout=60.0)
        except queue.Empty:
            log.debug("worker %d break: no jobs")
            break

        if job is None:
            log.debug("worker %d break: stop signal from main thread")
            state.jobs.task_done()
            break

        try:
            is_repo = _worker_job(job, state, options)
            if is_repo:
                found += 1
        except FileNotFoundError:
            log.debug("Path not found: %s", job.path)
        except NotADirectoryError:
            log.debug("Invalid path: %s", job.path)
        except PermissionError:
            log.error("No permission to search '%s'", job.path)
        except TimeoutError:
            log.error("Directory read timeout on '%s'", job.path)
        except OSError as e:
            log.error("Failed to search '%s': %s", job.path, e,
                      exc_info=config.debug)
        finally:
            visited += 1
            state.jobs.task_done()

    log.debug("worker %d terminating (visited %d, found %d)",
              tid, visited, found)
    return found


def find_repos(
    path: Path,
    max_depth: int = 0,
    filter: Optional[RepoFilter] = RepoFilter(),
    hidden: bool = False,
) -> list[GitRepo]:
    log.info("Searching for repositories in '%s'...", path.absolute())

    options = FindOptions(max_depth, filter, hidden)
    state = FindState(
        jobs=queue.Queue(),
        results=[],
        lock=threading.Lock(),
    )
    state.jobs.put(FindJob(path, 0))

    num_workers = max_threads(6)
    with ThreadPoolExecutor(max_workers=num_workers) as exec:
        fs = tuple(exec.submit(_worker, state, options)
                   for _ in range(num_workers))

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            log.warning("Aborting")
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
            log.warning("WARNING: Not waiting for workers that took"
                        " too long to terminate")

        found = 0
        for f in waited_fs.done:
            found += f.result()

    matches = len(state.results)

    if matches == 0:
        raise CommandError(f"No repositories found in '{path.absolute()}'")

    if matches < found:
        log.info("Found %d repositories in '%s' (total %d)",
                 matches, path.absolute(), found)
    else:
        log.info("Found %d repositories in '%s'", found, path.absolute())

    return state.results


def cmd_find(args: argparse.Namespace):
    repos = find_repos(
        args.path,
        max_depth=args.depth,
        filter=RepoFilter.create(args)
    )

    if args.output == OUTPUT_ABSOLUTE:
        for repo in repos:
            print(repo.path.absolute())
        return

    if args.output == OUTPUT_RESOLVE:
        for repo in repos:
            print(repo.path.resolve())
        return

    if args.output == OUTPUT_RELATIVE:
        for repo in repos:
            print(repo.path.relative_to(args.path))
        return

    if args.output == OUTPUT_URL:
        for repo in repos:
            remotes = repo.remotes()
            for url in remotes.values():
                print(url)
        return

    raise OptionError(f"Unexpected '--output' value '{args.output}'")
