import argparse
import concurrent.futures
import logging
import pygit2

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from .find import find_repos, RepoFilter
from .options import subparsers, filter_parser
from .utils import max_threads


log = logging.getLogger(__name__)

parser = subparsers.add_parser(
    "fetch",
    parents=[filter_parser],
    description="Fetch refs from remote repository",
    help="Fetch refs from remote repository",
)

parser.add_argument(
    "remote",
    nargs="?",
    default="",
    help="Remote name",
)

parser.add_argument(
    "-p", "--prune",
    action="store_true",
    help="Prune branches that no longer exist in remote",
)

parser.add_argument(
    "-a", "--all",
    action="store_true",
    help="Fetch from all remotes configured in a repository",
)


@dataclass
class FetchOptions:
    remote_name: str
    prune: bool
    all: bool


@dataclass
class FetchResult:
    repo: pygit2.Repository
    message: str = ""


def _worker(repo, options: FetchOptions) -> FetchResult:
    return FetchResult(repo)


def fetch_repos(
    repos: Collection[pygit2.Repository],
    remote_name: str = "",
    all: bool = False,
    prune: bool = False,
) -> list[FetchResult]:
    options = FetchOptions(
        remote_name=remote_name,
        all=all,
        prune=prune
    )

    num_workers = max_threads(3)
    with ThreadPoolExecutor(max_workers=num_workers) as exec:
        fs = (exec.submit(_worker, repo, options) for repo in repos)

        try:
            waited_fs = concurrent.futures.wait(fs, timeout=300.0)
        except KeyboardInterrupt:
            log.warning("Aborting")
            for f in fs:
                f.cancel()

        return [f.result() for f in waited_fs.done]


def cmd_fetch(args: argparse.Namespace):
    repos = find_repos(
        args.path,
        max_depth=1,
        filter=RepoFilter.create(args),
    )

    fetch_repos(
        repos,
        remote_name=args.remote,
        all=args.all,
        prune=args.prune,
    )
