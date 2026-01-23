import argparse
import concurrent.futures
import logging
import os
import pygit2
import queue
import threading

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

from .config import config, subparsers
from .exceptions import CommandError, ArgValueError
from .render import render_repos, render_parser, parse_render_options
from .utils import max_threads


log = logging.getLogger(__name__)

filter_parser = argparse.ArgumentParser(add_help=False)
filter_parser.add_argument("-n", "--name")
filter_parser.add_argument("-u", "--url", dest="remote_url")
filter_parser.add_argument("-b", "--branch")
filter_parser.add_argument("-C", "--case-sensitive", action="store_true")
filter_parser.add_argument("-E", "--exact", action="store_true")

search_parser = argparse.ArgumentParser(parents=[filter_parser], add_help=False)
search_parser.add_argument("path", type=Path)
search_parser.add_argument("-d", "--depth", type=int, default=0)
search_parser.add_argument("--hidden", action="store_true")

find_parser = subparsers.add_parser("find", parents=[search_parser, render_parser])


@dataclass
class FindJob:
    path: Path
    depth: int


@dataclass
class FindState:
    jobs: queue.Queue[Optional[FindJob]]
    aborted: bool = False


@dataclass
class FindOptions:
    path: Path
    depth: int
    hidden: bool
    filter: "FindFilter"


class FindFilter:
    def __init__(
        self,
        *,
        name: str,
        remote_url: str,
        branch: str,
        case_sensitive: bool,
        exact: bool,
    ):
        self.name = name if case_sensitive else name.lower()
        self.remote_url = remote_url if case_sensitive else remote_url.lower()
        self.branch = branch if case_sensitive else branch.lower()
        self.case_sensitive = case_sensitive
        self.exact = exact

    def __call__(self, repo: pygit2.Repository) -> bool:
        return (
            self.matches_name(repo)
            and self.matches_remote_url(repo)
            and self.matches_branch(repo)
        )

    def matches_name(self, repo: pygit2.Repository) -> bool:
        if not self.name:
            return True

        name = PurePath(repo.workdir).name
        return self._matches(self.name, name)

    def matches_remote_url(self, repo: pygit2.Repository) -> bool:
        if not self.remote_url:
            return True

        for name in repo.remotes.names():
            if name is None:
                continue

            url = repo.remotes[name].url

            if url is None:
                continue

            if self._matches(self.remote_url, url):
                return True

        return False

    def matches_branch(self, repo: pygit2.Repository) -> bool:
        if not self.branch:
            return True

        if repo.head_is_unborn or repo.head_is_detached:
            return False

        return self._matches(self.branch, repo.head.name)

    def _matches(self, query: str, value: str):
        _value = value if self.case_sensitive else value.lower()

        if self.exact:
            return query == _value

        return query in _value


def _worker_job(
    job: FindJob, state: FindState, options: FindOptions
) -> Optional[pygit2.Repository]:
    if options.hidden or not job.path.name.startswith("."):
        if state.aborted:
            return None

        path = pygit2.discover_repository(job.path.joinpath(".git"))
    else:
        path = None

    if path is not None:
        repo = pygit2.Repository(path)

        if state.aborted:
            return None

        if options.filter(repo):
            log.debug("find: Found repository %s", job.path)
            return repo

    elif options.depth <= 0 or job.depth < options.depth:
        with os.scandir(job.path) as it:
            for entry in it:
                if state.aborted:
                    break

                if not options.hidden and entry.name.startswith("."):
                    continue

                if entry.is_dir(follow_symlinks=False):
                    state.jobs.put_nowait(FindJob(Path(entry.path), job.depth + 1))

    return None


def _worker(state: FindState, options: FindOptions) -> list[pygit2.Repository]:
    tid = threading.get_native_id()
    n_visited = 0

    results: list[pygit2.Repository] = []

    while True:
        if state.aborted:
            log.debug("find: thread %d abort")
            break

        try:
            job = state.jobs.get(timeout=60.0)
        except queue.Empty:
            log.debug("find: thread %d timeout", tid)
            break

        if job is None:
            state.jobs.task_done()
            break

        if state.aborted:
            log.debug("find: thread %d abort")
            state.jobs.task_done()
            break

        try:
            repo = _worker_job(job, state, options)
            if repo:
                results.append(repo)
        except FileNotFoundError:
            if config.debug:
                log.debug("find: path not found: %s", job.path)
        except NotADirectoryError:
            if config.debug:
                log.debug("find: path invalid: %s", job.path)
        except PermissionError:
            log.error("find: %s: No permission to search")
        except OSError as e:
            log.error("find: %s: ERROR: %s", job.path, e)
        except pygit2.GitError as e:
            log.error("find: %s: GIT ERROR: %s", job.path, e)
        finally:
            state.jobs.task_done()

    if config.debug:
        log.debug("find: worker %d: visited %d, found %d", tid, n_visited, len(results))

    return results


def find_repos(
    path: Path,
    depth: int,
    hidden: bool = False,
    name: str = "",
    remote_url: str = "",
    branch: str = "",
    case_sensitive: bool = False,
    exact: bool = False,
) -> list[pygit2.Repository]:
    if not path.is_dir():
        raise ArgValueError(f"'{path}' is not a directory", arg="path")

    if depth > 0:
        log.info("Searching for repositories in '%s' (depth: %d)", path, depth)
    else:
        log.info("Searching for repositories in '%s'", path)

    state = FindState(jobs=queue.Queue())
    state.jobs.put_nowait(FindJob(path, 0))

    options = FindOptions(
        path=path,
        depth=depth,
        hidden=hidden,
        filter=FindFilter(
            name=name if name else "",
            remote_url=remote_url if remote_url else "",
            branch=branch if branch else "",
            case_sensitive=case_sensitive,
            exact=exact,
        ),
    )

    n_thread = max_threads(4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_thread) as exec:
        fs = tuple(exec.submit(_worker, state, options) for _ in range(n_thread))

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            log.warning("find: Aborting")
            state.aborted = True
            raise

        for _ in range(n_thread):
            state.jobs.put_nowait(None)

        try:
            state.jobs.join()
        except KeyboardInterrupt:
            log.warning("find: Aborting")
            state.aborted = True
            raise

        try:
            waited_fs = concurrent.futures.wait(fs, timeout=30.0)
        except KeyboardInterrupt:
            log.warning("find: Aborting")
            raise

        if waited_fs.not_done:
            raise CommandError("find: Search result aggregation timed out")

        results = [repo for f in waited_fs.done for repo in f.result()]

    log.info("Search complete: %d found\n", len(results))

    return results


def find_repos_args(args):
    return find_repos(
        path=args.path.resolve(),
        depth=args.depth,
        hidden=args.hidden,
        name=args.name,
        remote_url=args.remote_url,
        branch=args.branch,
        case_sensitive=args.case_sensitive,
        exact=args.exact,
    )


def cmd_find(args: argparse.Namespace):
    repos = find_repos_args(args)
    render_repos(repos, parse_render_options(args))
