from collections.abc import Collection, Iterable
import logging
from pathlib import Path
import typer
from typing import Annotated
from urllib.parse import urlparse

from grm import github
from grm.config import CloneOptions, RemoteProvider
from grm.find import find_repos
from grm.git import GitException, GitRepository
from grm.util import GrmExit, InvalidArgsError, RemoteRepository, matches_globs, confirm


LIST_SEP = "\n - "

app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("clone")
def cmd_clone(
    owner: Annotated[str, typer.Argument(
        help="Remote provider account or organization(group) name",
    )],
    globs: Annotated[list[str], typer.Option(
        "-g", "--glob",
        default_factory=list,
        help="UNIX-style glob filter (clone URL path, case-insensitive)."
             "Prefix with '!' to exclude matching repositories"
    )],
    path: Annotated[str, typer.Option(
        "-p", "--path",
        help="Path template to use for cloned repositories "
             "(supported fields: 'owner', 'name')",
    )] = "{name}",
    provider: Annotated[str, typer.Option(
        "--provider",
        help="Remote repository provider (possible values: 'github')",
    )] = "github",
    host: Annotated[str, typer.Option(
        "--host",
        help="Remote repository provider hostname (for self-hosted providers)"
    )] = "",
    prune: Annotated[bool, typer.Option(
        "--prune",
        help="Permanently delete repositories that no longer exist "
             "in remote (mutually exclusive with '--archive')"
    )] = False,
    archive: Annotated[bool, typer.Option(
        "--archive",
        help="Move repositories that no longer exist in remote to "
             "the archive directory (mutually exclusive with '--prune')"
    )] = False,
    yes: Annotated[bool, typer.Option(
        "-y", "--yes",
        help="Clone repositories without asking for confirmation",
    )] = False
):
    opts = CloneOptions(
        owner=owner,
        path=path,
        provider=provider,
        host=host,
        prune=prune,
        archive=archive,
        globs=globs,
    )
    log.debug("opts: %s", opts)

    clone_repos(
        Path.cwd(),
        opts,
        local_repos=find_repos(Path.cwd()),
        confirm_prune=not yes,
    )


def clone_repos(
    path: Path,
    opts: CloneOptions,
    *,
    local_repos: Collection[GitRepository] = [],
    confirm_prune: bool = False,
) -> list[GitRepository]:
    if opts.prune and opts.archive:
        raise ValueError("Set either one of 'prune' or 'archive' -- not both")

    new_repos, existing_repos = _list_remote_repos(opts, local_repos)
    prunable_repos = _list_prunable_repos(
        new_repos + existing_repos,
        local_repos
    )
    _log_clone_plan(opts, new_repos, existing_repos, prunable_repos)

    if opts.prune and prunable_repos and confirm_prune:
        repositories = "repository" if len(prunable_repos) == 1 \
                else "repositories"

        if not confirm(
            f"Permanently delete(prune) {len(prunable_repos)} "
            f"{repositories}? You cannot undo this action."
        ):
            raise GrmExit()

    success, failed = _clone_repos(path, opts.path, new_repos)

    return []


def _clone_repos(
    path: Path,
    subpath: str,
    remote_repos: list[RemoteRepository],
):
    success: list[GitRepository] = []
    failed: list[RemoteRepository] = []

    for remote_repo in remote_repos:
        owner, name = remote_repo.parse_url()
        clone_path = path / subpath.format(owner=owner, name=name)

        try:
            repo = GitRepository.clone(remote_repo.url, clone_path)
            success.append(repo)
        except GitException as exc:
            log.error("%s", exc)
            failed.append(remote_repo)
            continue

    return success, failed


def _log_clone_result(
    success: list[GitRepository],
    failed: list[RemoteRepository],
    pruned: list[GitRepository],
):
    ...


def _list_prunable_repos(
    remote_repos: Collection[RemoteRepository],
    local_repos: Collection[GitRepository],
) -> list[GitRepository]:
    """
    Return repositories from 'local_repos' that does not have a matching
    repository in 'remote_repos'
    """
    remote_urls = set(
        _parse_prune_condition(repo.url)
        for repo in remote_repos
    )

    return [
        repo
        for repo in local_repos
        for remote in repo.list_remotes()
        if _parse_prune_condition(remote.url) not in remote_urls
    ]


def _parse_prune_condition(url: str):
    """
    A local repository is considered prunable if there are no
    remote repositories with a remote URL that has the same
    hostname and path
    """
    p_url = urlparse(url)
    return p_url.netloc, p_url.path


def _list_remote_repos(
    opts: CloneOptions,
    local_repos: Iterable[GitRepository],
):
    log.info("Listing %s repositories (%s)...", opts.provider, opts.owner)
    existing_urls: set[str] = set(
        remote.url
        for repo in local_repos
        for remote in repo.list_remotes()
    )

    new_repos: list[RemoteRepository] = []
    existing_repos: list[RemoteRepository] = []

    for remote_repo in _fetch_remote_repos(opts.provider, opts.owner, opts.globs):
        if remote_repo.url in existing_urls:
            existing_repos.append(remote_repo)
        else:
            new_repos.append(remote_repo)

    return new_repos, existing_repos


def _fetch_remote_repos(
    provider: str,
    owner: str,
    globs: list[str]
) -> Iterable[RemoteRepository]:
    try:
        _provider = RemoteProvider(provider)
    except ValueError:
        raise InvalidArgsError(f"Invalid provider '{provider}'")

    if _provider == RemoteProvider.GITHUB:
        remote_repos = github.list_repos(owner)
    else:
        raise RuntimeError()

    for remote_repo in remote_repos:
        if len(globs) == 0 or matches_globs(remote_repo.path(), globs):
            yield remote_repo


def _log_clone_plan(
    opts: CloneOptions,
    new_repos: list[RemoteRepository],
    existing_repos: list[RemoteRepository],
    prunable_repos: list[GitRepository],
):
    if existing_repos:
        repositories = "repository" if len(existing_repos) == 1 \
                else "repositories"

        if log.isEnabledFor(logging.DEBUG):
            existing_urls = [r.url for r in existing_repos]
            existing_urls.sort()
            log.debug(
                "Found %d existing %s (already cloned): \n - %s",
                len(existing_repos),
                repositories,
                "\n - ".join(existing_urls),
            )
        else:
            log.info(
                "Found %d existing %s (already cloned)",
                len(existing_repos),
                repositories,
            )

    if new_repos and log.isEnabledFor(logging.INFO):
        repositories = "repository" if len(new_repos) == 1 \
                else "repositories"

        new_urls = [r.url for r in new_repos]
        new_urls.sort()

        log.info(
            "Found %d new %s (will be cloned): \n - %s",
            len(new_urls),
            repositories,
            "\n - ".join(new_urls),
        )
    else:
        log.info("Found 0 new repositories")

    if prunable_repos:
        repositories = "repository" if len(prunable_repos) == 1 \
                else "repositories"

        prunable_paths = [str(r.path) for r in prunable_repos]
        prunable_paths.sort()

        if opts.prune:
            action = "deleted"
        elif opts.archive:
            action = "archived"
        else:
            action = "left as-is"

        log.log(
            logging.WARNING if opts.prune else logging.INFO,
            "Found %d prunable %s (will be %s) \n - %s",
            len(prunable_paths),
            repositories,
            action,
            "\n - ".join(prunable_paths)
        )
