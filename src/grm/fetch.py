import argparse
import logging
import pygit2

from pygit2.enums import FetchPrune

from .config import config, subparsers, relative_workdir
from .credential import RemoteCallbacks
from .exceptions import ProcedureError
from .find import search_parser, find_repos_args
from .utils import pl


log = logging.getLogger(__name__)

fetch_parser = subparsers.add_parser("fetch", parents=[search_parser])
fetch_parser.add_argument(
    "-r", "--remote", default="", help="Remote name", dest="remote_name"
)
fetch_parser.add_argument("-p", "--prune", action="store_true")

remote_callbacks = RemoteCallbacks()


def fetch_repo(
    repo: pygit2.Repository, remote_name: str = "", prune: bool = False
) -> tuple[pygit2.Repository, bool]:
    if remote_name:
        try:
            remotes = [repo.remotes[remote_name]]
        except KeyError:
            log.error(
                "fetch: %s: ERROR: Remote '%s' not found",
                relative_workdir(repo),
                remote_name,
            )
            return repo, False
    else:
        # all remotes
        remotes = [repo.remotes[name] for name in repo.remotes.names() if name]

    if not remotes:
        log.warning("fetch: %s: WARNING: No remotes configured", relative_workdir(repo))
        return repo, True

    _prune = FetchPrune.PRUNE if prune else FetchPrune.UNSPECIFIED

    success = True

    for remote in remotes:
        log.info("fetch: %s: Fetching '%s'", relative_workdir(repo), remote.name)
        try:
            remote.fetch(prune=_prune, callbacks=remote_callbacks)
        except ProcedureError as e:
            log.error(
                "fetch: %s: ERROR: Fetch failed (%s) -- %s",
                relative_workdir(repo),
                remote.name,
                e,
            )
            success = False
        except pygit2.GitError as e:
            log.error(
                "fetch: %s: GIT ERROR: Fetch failed (%s) -- %s",
                relative_workdir(repo),
                remote_name,
                e,
                exc_info=config.debug,
            )
            success = False

    return repo, success


def fetch_repos(
    repos: list[pygit2.Repository], remote_name: str = "", prune: bool = False
) -> list[pygit2.Repository]:
    n_total = len(repos)
    log.info("Fetching %d %s", n_total, pl(n_total, "repository", "repositories"))

    results = list(
        fetch_repo(repo, remote_name=remote_name, prune=prune) for repo in repos
    )

    failed_repos = [repo for repo, success in results if not success]
    n_failed = len(failed_repos)
    n_success = n_total - n_failed

    if failed_repos:
        failed_repo_paths = ", ".join(
            str(relative_workdir(repo)) for repo in failed_repos
        )
        log.error(
            "fetch: %d failed %s: %s",
            n_failed,
            pl(n_failed, "repository", "repositories"),
            failed_repo_paths,
        )

    log.info("Fetch complete: %d success, %d failed\n", n_success, n_failed)

    return [repo for repo, success in results if success]


def fetch_repos_args(
    repos: list[pygit2.Repository], args: argparse.Namespace
) -> list[pygit2.Repository]:
    return fetch_repos(repos, remote_name=args.remote_name, prune=args.prune)


def cmd_fetch(args: argparse.Namespace):
    repos = find_repos_args(args)
    fetch_repos_args(repos, args)
