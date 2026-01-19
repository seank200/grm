import argparse
import concurrent.futures
import logging
import pygit2
import subprocess

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from pygit2.enums import FetchPrune

from .exceptions import CommandError
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
    "path",
    nargs="?",
    default=Path.cwd(),
    type=Path,
    help="repository search path [default: (current working directory)]",
)

parser.add_argument(
    "-d", "--depth",
    default=0,
    type=int,
    help="maximum search depth (0 for no recursion limit) [default: 0]"
)

parser.add_argument(
    "--fetch-depth",
    default=0,
    type=int,
    help="Number of commits from the tip of each remote branch history "
         "to fetch [default: 0 (all history is fetched)]",
)

parser.add_argument(
    "--remote",
    nargs="?",
    default="",
    help="name of remote to fetch (e.g. 'origin') [default: '' (fetch"
    " all repositories)]",
    dest="remote_name",
)

parser.add_argument(
    "--prune",
    action="store_true",
    help="Prune branches that no longer exist in remote",
)


@dataclass
class FetchOptions:
    remote_name: str
    prune: bool
    depth: int


@dataclass
class FetchResult:
    repo: pygit2.Repository
    success: bool = True


@dataclass(frozen=True)
class RemoteCredentials:
    protocol: str
    host: str
    path: str
    username: str
    password: str


def is_scp_ish(url: str) -> bool:
    if url.startswith("ssh://"):
        return True

    if url.find("://") >= 0:
        return False

    colon_i = url.find(":")
    slash_i = url.find("/")

    return slash_i > colon_i


def parse_scp_ish(url: str) -> str:
    p_input = ""
    start = 0
    at_i = url.find("@")
    if at_i > 0:
        p_input += f"username={url[:at_i]}\n"
        start = at_i + 1

    colon_i = url.find(":", start)
    if colon_i > 0:
        p_input += f"host={url[start:colon_i]}\n"
        start = colon_i + 1

    if start > 0:
        p_input += f"path={url[start:]}"

    return p_input


class GitCredentialRemoteCallbacks(pygit2.RemoteCallbacks):
    def credentials(
        self,
        url: str,
        username_from_url: str | None,
        allowed_types: pygit2.enums.CredentialType,
    ):
        """Call git-credentials to retrieve remote credentials"""
        if is_scp_ish(url):
            p_input = parse_scp_ish(url)
        else:
            p_input = ""

        if not p_input:
            p_input = f"url={url}\n\n"

        proc = subprocess.run(
            "git credential fill".split(" "),
            input=p_input,
            text=True,
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

        properties = ""
        username = ""
        password = ""

        for line in proc.stdout.splitlines():
            try:
                key, value = line.split("=", 1)
            except ValueError:
                continue

            if key == "username":
                username = value
            elif key == "password":
                password = value
            else:
                properties += " " + line

        if username and password:
            log.debug("Found remote credentials for '%s':%s", url, properties)
            return pygit2.credentials.UserPass(username, password)
        elif username:
            log.debug("Found remote credentials for '%s':%s", url, properties)
            return pygit2.credentials.Username(username)
        else:
            raise CommandError("Remote authentication is required, but "
                               "no credentials were found")


remote_callbacks = GitCredentialRemoteCallbacks()


def _worker(repo: pygit2.Repository, options: FetchOptions) -> FetchResult:
    if options.remote_name:
        remote = repo.remotes.get()
        if remote is None:
            log.warning("fetch: %s: Remote '%s' was not found",
                        repo.workdir, options.remote_name)

            return FetchResult(repo=repo, success=False)
        else:
            remotes = [remote]
    else:
        remotes = repo.remotes

    success = True
    for remote in remotes:
        log.info("fetch: %s: fetching '%s'", repo.workdir, remote.name)

        prune = FetchPrune.PRUNE if options.prune else FetchPrune.UNSPECIFIED
        try:
            remote.fetch(
                prune=prune,
                callbacks=remote_callbacks,
                depth=options.depth,
            )
        except pygit2.GitError as e:
            log.error("fetch: %s: failed to fetch '%s'. %s",
                      repo.workdir, remote.name, e, exc_info=True)
            success = False
        except CommandError as e:
            log.error("fetch: %s: unable to fetch '%s'. %s",
                      repo.workdir, remote.name, e)
            success = False

    return FetchResult(repo, success)


def fetch_repos(
    repos: Collection[pygit2.Repository],
    remote_name: str = "",
    prune: bool = False,
    depth: int = 0,
) -> list[FetchResult]:
    """
    Fetch remote refs from repositories

    Args:
        repos: Repositories
        remote_name: Name of the remote to fetch (if not specified,
          fetch all remotes)
        prune: Prune refs that no longer exist in the remote repository
        depth: Number of commits from the tip of each remote branch
          history to fetch [default: 0 (all history is fetched)]

    Returns:
        A list of `FetchResult` instances, containing the reference
        to the repository and a boolean flag indicating whether the
        fetch was successful.
    """

    options = FetchOptions(
        remote_name=remote_name,
        prune=prune,
        depth=depth,
    )

    num_workers = max_threads(4)
    with ThreadPoolExecutor(max_workers=num_workers) as exec:
        fs = (exec.submit(_worker, repo, options) for repo in repos)

        try:
            waited_fs = concurrent.futures.wait(fs, timeout=300.0)
        except KeyboardInterrupt:
            log.warning("Aborting fetch")
            for f in fs:
                f.cancel()
            raise

        return [f.result() for f in waited_fs.done]


def cmd_fetch(args: argparse.Namespace):
    repos = find_repos(
        args.path,
        max_depth=1,
        filter=RepoFilter.create(args),
    )

    results = fetch_repos(
        repos,
        remote_name=args.remote_name,
        prune=args.prune,
        depth=args.fetch_depth,
    )

    results.sort(key=lambda r: r.repo.workdir)

    success_repos = list(r.repo.workdir for r in results if r.success)
    failed_repos = list(r.repo.workdir for r in results if not r.success)

    if success_repos:
        log.info("fetch: success (%d/%d):\n  - %s",
                 len(success_repos), len(repos), "\n  - ".join(success_repos))

    if failed_repos:
        log.warning("fetch: failed (%d/%d):\n  - %s",
                    len(failed_repos), len(repos), "\n  - ".join(failed_repos))

    if failed_repos:
        log.error("fetch: completed %d (success %d, failed %d)",
                  len(repos), len(success_repos), len(failed_repos))
    else:
        log.info("fetch: completed %d (success %d, failed 0)",
                 len(repos), len(success_repos))

    if len(failed_repos) > 0:
        return 1

    return 0
