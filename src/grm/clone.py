from collections.abc import Iterator
from datetime import datetime
import logging
from pathlib import Path
import shutil
import sys
from typing import Annotated, Optional
import typer

from grm.config import (
    CloneOptions,
    FindOptions,
    RemoteProvider,
    ARCHIVE_DIR,
)
from grm.find import find_repos
from grm.git import GitException, GitRepository
from grm.github import list_repos as list_github_repos
from grm.util import RemoteRepository, InvalidArgsError, confirm, matches_globs


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("clone", help="Clone new remote repositories")
def cmd_clone(
    owner: Annotated[str, typer.Argument(
        help="Remote repository owner (account or organization/group name)",
    )],
    provider: Annotated[RemoteProvider, typer.Option(
        help="Remote repository provider name",
    )] = RemoteProvider.GITHUB,
    hostname: Annotated[Optional[str], typer.Option(
        help="Hostname of the remote provider (for self-hosted providers)",
    )] = None,
    filters: Annotated[list[str], typer.Option(
        "-g", "--glob",
        help="Repository clone URL path filter"
    )] = [],
    path_template: Annotated[str, typer.Option(
        "--path",
        help="Python template string for local clone directory path "
             "(supported fields: 'owner', 'name')",
    )] = "{name}",
    prune: Annotated[bool, typer.Option(
        "--prune",
        help="Remove repositories that no longer exist in remote"
    )] = False,
    archive: Annotated[bool, typer.Option(
        "--archive",
        help="When pruning, archive repositories instead of pruning",
    )] = False,
    no_confirm: Annotated[bool, typer.Option(
        "-y", "--yes",
        help="Disable confirmation prompts before pruning repositories"
    )] = False,
):
    if prune and archive:
        raise InvalidArgsError("Set either 'prune' or 'archive', not both")

    clone_repos(Path.cwd(), [CloneOptions(
        owner=owner,
        provider=provider.value,
        hostname=hostname,
        filters=filters,
        path_template=path_template,
        prune=prune,
        archive=archive,
    )], no_confirm)


def clone_repos(path: Path, opts: list[CloneOptions], no_confirm: bool):
    clone_jobs: list[tuple[CloneOptions, RemoteRepository]] = []
    existing_repos: list[GitRepository] = []
    prune_jobs: list[GitRepository] = []
    archive_jobs: list[GitRepository] = []

    for opt in opts:
        new_repos, _existing_repos, prunable_repos = _list_repos(
            path,
            opt.provider,
            opt.owner,
            opt.hostname,
            opt.path_template,
            opt.filters,
        )

        existing_repos.extend(_existing_repos)
        clone_jobs.extend((opt, repo) for repo in new_repos)
        if opt.prune:
            prune_jobs.extend(prunable_repos)
        elif opt.archive:
            archive_jobs.extend(prunable_repos)

    _log_existing_repos(existing_repos)
    _log_jobs(clone_jobs, prune_jobs, archive_jobs)

    if prune_jobs:
        log.warning(
            "WARNING: This operation will PERMANENTLY delete (prune) "
            "%d %s. This action cannot be undone.",
            len(prune_jobs),
            "repository" if len(prune_jobs) <= 1 else "repositories",
        )

    if not no_confirm and sys.stdin.isatty():
        confirm()

    prune_success, prune_failed = _prune_repos(path, prune_jobs)
    archive_success, archive_failed = _archive_repos(path, archive_jobs)
    clone_success, clone_failed = _clone_new_repos(path, clone_jobs)

    _log_results(
        path,
        clone_success,
        clone_failed,
        prune_success,
        prune_failed,
        archive_success,
        archive_failed,
    )

    return clone_success


def _clone_new_repos(
    path: Path,
    clone_jobs: list[tuple[CloneOptions, RemoteRepository]]
) -> tuple[
    list[tuple[RemoteRepository, GitRepository]],
    list[RemoteRepository]
]:
    if not clone_jobs:
        return [], []

    log.info(
        "Cloning %d new %s...",
        len(clone_jobs),
        "repository" if len(clone_jobs) <= 1 else "repositories",
    )
    log_format = f"[%{len(str(len(clone_jobs)))}d/%d] Cloning '%s' (%s)"

    success: list[tuple[RemoteRepository, GitRepository]] = []
    failed: list[RemoteRepository] = []

    for i, (opt, remote_repo) in enumerate(clone_jobs):
        clone_subpath = opt.path_template.format(
            owner=remote_repo.owner,
            name=remote_repo.name,
        )
        clone_path = path / clone_subpath

        log.info(
            log_format,
            i+1,
            len(clone_jobs),
            remote_repo.url,
            clone_path.relative_to(path),
        )

        try:
            repo = GitRepository.clone(remote_repo.url, clone_path)
            success.append((remote_repo, repo))
        except GitException as exc:
            log.error("ERROR: %s", exc)
            failed.append(remote_repo)

    return success, failed


def _prune_repos(
    path: Path,
    repos: list[GitRepository]
) -> tuple[list[GitRepository], list[GitRepository]]:
    if not repos:
        return [], []

    log.info(
        "Pruning %d %s...",
        len(repos),
        "repository" if len(repos) == 1 else "repositories",
    )
    log_format = f"[%{len(str(len(repos)))}d/%d] Pruning '%s'"

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    for i, repo in enumerate(repos):
        log.info(
            log_format,
            i+1,
            len(repos),
            repo.path.relative_to(path),
        )

        try:
            shutil.rmtree(repo.path)
            success.append(repo)
        except OSError as exc:
            log.error(
                "ERROR: Failed to prune '%s'. %s",
                repo.path,
                exc,
                exc_info=log.isEnabledFor(logging.DEBUG),
            )
            failed.append(repo)

    return success, failed


def _archive_repos(
    path: Path,
    repos: list[GitRepository]
) -> tuple[list[GitRepository], list[GitRepository]]:
    if not repos:
        return [], []

    archive_dir = path / ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "Archiving %d %s (%s)...",
        len(repos),
        "repository" if len(repos) == 1 else "repositories",
        archive_dir,
    )
    log_format = f"[%{len(str(len(repos)))}d/%d] Archiving '%s' to '%s'"

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    for i, repo in enumerate(repos):
        archive_target = archive_dir / repo.name
        if archive_target.exists():
            archive_target = archive_dir / f"{repo.name}_{datetime.now().timestamp()}"
        if archive_target.exists():
            log.error(
                "ERROR: Failed to archive '%s'. Path '%s' already exists",
                repo.path,
                archive_target,
            )
            continue

        log.info(
            log_format,
            i+1,
            len(repos),
            repo.path.relative_to(path),
            archive_target.relative_to(path),
        )

        try:
            shutil.move(repo.path, archive_target)
            success.append(repo)
        except OSError as exc:
            log.error(
                "ERROR: Failed to archive '%s'. %s",
                repo.path,
                exc,
            )
            failed.append(repo)

    return success, failed


def _list_repos(
    path: Path,
    provider: str,
    owner: str,
    hostname: str | None,
    path_template: str,
    filters: list[str],
):
    new_repos: list[RemoteRepository] = []
    prunable_repos: set[GitRepository] = _find_existing_repos(
        path,
        owner,
        path_template
    )
    existing_repos: list[GitRepository] = []

    url_repos_map: dict[str, list[GitRepository]] = {}
    for repo in prunable_repos:
        for remote in repo.list_remotes():
            try:
                url_repos_map[remote.url].append(repo)
            except KeyError:
                url_repos_map[remote.url] = [repo]

    for remote_repo in _list_remote_repos(provider, owner, hostname):
        if filters and not matches_globs(remote_repo.path, filters):
            log.debug("Excluding '%s' (filtered)", remote_repo.path)
            continue

        repos = url_repos_map.get(remote_repo.url)
        if repos:
            for repo in repos:
                prunable_repos.remove(repo)
                existing_repos.append(repo)
        else:
            new_repos.append(remote_repo)

    return new_repos, existing_repos, prunable_repos


def _list_remote_repos(
    provider: str,
    owner: str,
    hostname: str | None
) -> Iterator[RemoteRepository]:
    if provider == RemoteProvider.GITHUB.value:
        return list_github_repos(owner, hostname=hostname)

    raise InvalidArgsError(f"Unsupported remote provider '{provider}'")


def _find_existing_repos(
    path: Path,
    owner: str,
    path_template: str,
):
    sub_path_glob = path_template.format(owner=owner, name="*")
    return find_repos(path, FindOptions(
        depth=1,
        hidden="." in path_template,
        filters=[sub_path_glob]
    ))


def _log_jobs(
    clone_jobs: list[tuple[CloneOptions, RemoteRepository]],
    prune_jobs: list[GitRepository],
    archive_jobs: list[GitRepository],
):
    if clone_jobs:
        if log.isEnabledFor(logging.INFO):
            clone_urls = [repo.url for _, repo in clone_jobs]
            clone_urls.sort()
            log.info(
                "Found %d new %s (will be cloned)\n - %s",
                len(clone_jobs),
                "repository" if len(clone_jobs) == 1 else "repositories",
                "\n - ".join(clone_urls)
            )
    else:
        log.info("No new repositories found to clone")

    if prune_jobs and log.isEnabledFor(logging.WARNING):
        prune_paths = [str(repo.path) for repo in prune_jobs]
        prune_paths.sort()

        log.warning(
            "Found %d prunable %s (will be PERMANENTLY DELETED)\n - %s",
            len(prune_paths),
            "repository" if len(prune_paths) <= 1 else "repositories",
            "\n - ".join(prune_paths),
        )

    if archive_jobs and log.isEnabledFor(logging.WARNING):
        archive_paths = [str(repo.path) for repo in archive_jobs]
        archive_paths.sort()

        log.warning(
            "Found %d archivable %s (will be moved)\n - %s",
            len(archive_paths),
            "repository" if len(archive_paths) <= 1 else "repositories",
            "\n - ".join(archive_paths),
        )


def _log_existing_repos(existing_repos: list[GitRepository]):
    if existing_repos and log.isEnabledFor(logging.DEBUG):
        existing_paths = [
            str(repo.path)
            for repo in existing_repos
        ]
        existing_paths.sort()

        log.debug(
            "Found %d existing %s (already cloned)\n - %s",
            len(existing_paths),
            "repository" if len(existing_paths) <= 1 else "repositories",
            "\n - ".join(existing_paths)
        )
    else:
        log.info(
            "Found %d existing %s (already cloned)",
            len(existing_repos),
            "repository" if len(existing_repos) <= 1 else "repositories",
        )


def _log_results(
    path: Path,
    clone_success: list[tuple[RemoteRepository, GitRepository]],
    clone_failed: list[RemoteRepository],
    prune_success: list[GitRepository],
    prune_failed: list[GitRepository],
    archive_success: list[GitRepository],
    archive_failed: list[GitRepository],
) -> None:
    if log.isEnabledFor(logging.DEBUG):
        if clone_success:
            log.debug(
                "Cloned %d/%d %s: \n - %s",
                len(clone_success),
                len(clone_success) + len(clone_failed),
                "repository" if len(clone_success) <= 1 else "repositories",
                "\n - ".join(
                    f"{remote_repo.url} ({repo.path.relative_to(path)})"
                    for remote_repo, repo in clone_success
                )
            )
        if prune_success:
            log.debug(
                "Pruned %d/%d %s: \n - %s",
                len(prune_success),
                len(prune_success) + len(prune_failed),
                "repository" if len(prune_success) <= 1 else "repositories",
                "\n - ".join(
                    str(repo.path.relative_to(path))
                    for repo in prune_success
                )
            )

        if archive_success:
            log.debug(
                "Archived %d/%d %s: \n - %s",
                len(archive_success),
                len(archive_success) + len(archive_failed),
                "repository" if len(archive_success) <= 1 else "repositories",
                "\n - ".join(
                    str(repo.path.relative_to(path))
                    for repo in archive_success
                )
            )
    else:
        log.info(
            "Cloned %d/%d, pruned %d/%d, archived %d/%d repositories",
            len(clone_success),
            len(clone_success) + len(clone_failed),
            len(prune_success),
            len(prune_success) + len(prune_failed),
            len(archive_success),
            len(archive_success) + len(archive_failed),
        )

    if clone_failed and log.isEnabledFor(logging.ERROR):
        log.error(
            "Failed to clone %d/%d %s: \n - %s",
            len(clone_failed),
            len(clone_success) + len(clone_failed),
            "repository" if len(clone_failed) <= 1 else "repositories",
            "\n - ".join(repo.url for repo in clone_failed)
        )

    if prune_failed and log.isEnabledFor(logging.ERROR):
        log.error(
            "Failed to prune %d/%d %s: \n - %s",
            len(prune_failed),
            len(prune_success), len(prune_failed),
            "repository" if len(prune_failed) <= 1 else "repositories",
            "\n - ".join(
                str(repo.path.relative_to(path))
                for repo in prune_failed
            ),
        )

    if archive_failed and log.isEnabledFor(logging.ERROR):
        log.error(
            "Failed to archive %d/%d %s to '%s': \n - %s",
            len(archive_failed),
            len(archive_success) + len(archive_failed),
            "repository" if len(archive_failed) <= 1 else "repositories",
            "\n - ".join(
                str(repo.path.relative_to(path))
                for repo in archive_failed
            )
        )
