from collections.abc import Collection, Iterable
from datetime import datetime
import logging
from pathlib import Path, PurePath, PurePosixPath
import shutil
from urllib.parse import urlparse

from grm.config import CloneOptions, FindOptions, RemoteProvider
from grm.find import find_repos
from grm.git import GitException, GitRepository
from grm.github import GH_HOSTNAME, list_repos as github_list_repos
from grm.util import GrmException, RemoteRepository, TqdmWrapper, matches_globs


log = logging.getLogger(__name__)


def clone_repos(
    workspace: Path,
    options_list: list[CloneOptions],
) -> set[GitRepository]:
    if not any(o.enabled for o in options_list):
        return set()

    now = datetime.now()

    clone_jobs: list[tuple[Path, RemoteRepository]] = []
    existing_repos: set[GitRepository] = set()
    prunable_repos: set[GitRepository] = set()
    archive_jobs: list[tuple[Path, GitRepository]] = []

    clone_plan_failed: list[RemoteRepository] = []
    archive_plan_failed: list[GitRepository] = []

    for options in options_list:
        if not options.enabled:
            continue

        if not options.owner:
            raise GrmException("'owner' cannot be empty")

        _new, _existing, _prunable = _list_repos(workspace, options)

        _clone_jobs, _clone_plan_failed = _plan_clone_jobs(
            workspace,
            _new,
            options,
        )
        clone_jobs.extend(_clone_jobs)
        clone_plan_failed.extend(_clone_plan_failed)

        existing_repos.update(_existing)

        if options.archive:
            _archive_jobs, _archive_plan_failed = _plan_archive_jobs(
                _prunable,
                options,
                now,
            )
            archive_jobs.extend(_archive_jobs)
            archive_plan_failed.extend(_archive_plan_failed)
        else:
            prunable_repos.update(_prunable)

    _log_plan(
        workspace,
        clone_jobs,
        existing_repos,
        prunable_repos,
        archive_jobs
    )

    prune_success, prune_failed = _prune_repos(workspace, prunable_repos)
    archive_success, archive_failed = _archive_repos(workspace, archive_jobs)
    clone_success, clone_failed = _clone_repos(clone_jobs)
    archive_failed.extend(archive_plan_failed)
    clone_failed.extend(clone_plan_failed)

    _log_results(
        workspace,
        clone_success,
        clone_failed,
        prune_success,
        prune_failed,
        archive_success,
        archive_failed,
    )

    return clone_success


def _plan_clone_jobs(
    workspace: Path,
    new_repos: Collection[RemoteRepository],
    options: CloneOptions,
):
    clone_jobs: list[tuple[Path, RemoteRepository]] = []
    clone_plan_failed: list[RemoteRepository] = []

    for repo in new_repos:
        try:
            clone_path = _resolve_clone_path(
                workspace,
                repo,
                options.path
            )
        except GrmException as exc:
            clone_plan_failed.append(repo)
            log.error("ERROR: %s", exc)
            continue

        clone_jobs.append((clone_path, repo))

    return clone_jobs, clone_plan_failed


def _plan_archive_jobs(
    prunable_repos: Collection[GitRepository],
    options: CloneOptions,
    now: datetime,
):
    archive_jobs: list[tuple[Path, GitRepository]] = []
    archive_plan_failed: list[GitRepository] = []

    for repo in prunable_repos:
        try:
            archive_path = _resolve_archive_path(
                repo,
                options.archive,
                options.owner,
                now,
            )
        except GrmException as exc:
            log.error("ERROR: %s", exc)
            archive_plan_failed.append(repo)
            continue

        archive_jobs.append((archive_path, repo))

    return archive_jobs, archive_plan_failed


def _clone_repos(
    jobs: Collection[tuple[Path, RemoteRepository]]
) -> tuple[set[GitRepository], list[RemoteRepository]]:
    if not jobs:
        return set(), []

    log.info(
        "Cloning %d repositor%s...",
        len(jobs),
        "y" if len(jobs) <= 1 else "ies",
    )

    success: set[GitRepository] = set()
    failed: list[RemoteRepository] = []

    with TqdmWrapper("Cloning", total=len(jobs)) as bar:
        for clone_path, remote_repo in jobs:
            log.info(
                "Cloning '%s'",
                remote_repo.url,
            )
            try:
                repo = GitRepository.clone(remote_repo.url, clone_path)
            except GitException as exc:
                failed.append(remote_repo)
                log.error("ERROR: %s", exc)
                continue
            finally:
                bar.update(1)

            success.add(repo)
            log.debug("Cloned '%s' (%s)", remote_repo.url, clone_path)

    return success, failed


def _prune_repos(
    workspace: Path,
    repos: Collection[GitRepository]
) -> tuple[list[GitRepository], list[GitRepository]]:
    if not repos:
        return [], []

    log.info(
        "Pruning %d repositor%s...",
        len(repos),
        "y" if len(repos) <= 1 else "ies",
    )

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    for repo in repos:
        log.debug("Pruning '%s'...", repo.path)

        try:
            repo.prune_worktrees()
        except GitException as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to prune repository '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        try:
            for worktree in repo.list_worktrees()[1:]:
                repo.remove_worktree(worktree)
        except GitException as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to prune repository '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        try:
            shutil.rmtree(repo.path)
        except OSError as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to prune repository '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        success.append(repo)
        log.info("Pruned '%s'", repo.path.relative_to(workspace))

    return success, failed


def _archive_repos(
    workspace: Path,
    jobs: Collection[tuple[Path, GitRepository]]
) -> tuple[list[tuple[Path, GitRepository]], list[GitRepository]]:
    if not jobs:
        return [], []

    log.info(
        "Archiving %d repositor%s...",
        len(jobs),
        "y" if len(jobs) <= 1 else "ies",
    )

    success: list[tuple[Path, GitRepository]] = []
    failed: list[GitRepository] = []

    for archive_path, repo in jobs:
        log.debug("Archiving '%s' -> '%s'...", repo.path, archive_path)

        try:
            repo.prune_worktrees()
        except GitException as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to archive '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        try:
            for worktree in repo.list_worktrees()[1:]:
                repo.remove_worktree(worktree)
        except GitException as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to archive '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        if archive_path.exists(follow_symlinks=False):
            failed.append(repo)
            log.error(
                "ERROR: Failed to archive '%s'. Path '%s' already exists",
                repo.path.relative_to(workspace),
                archive_path,
            )
            continue

        try:
            shutil.move(repo.path, archive_path)
        except OSError as exc:
            failed.append(repo)
            log.error(
                "ERROR: Failed to archive '%s'. %s",
                repo.path.relative_to(workspace),
                exc,
            )
            continue

        success.append((archive_path, repo))
        log.info(
            "Archived '%s' -> '%s'",
            repo.path.relative_to(workspace),
            archive_path,
        )

    return success, failed


def _list_repos(
    workspace: Path,
    options: CloneOptions,
) -> tuple[list[RemoteRepository], set[GitRepository], set[GitRepository]]:
    new_repos: list[RemoteRepository] = []
    existing_repos: set[GitRepository] = set()
    prunable_repos: set[GitRepository] = _find_local_repos(
        workspace,
        options.provider,
        options.hostname,
        options.owner,
        options.path,
    )

    url_repos_map: dict[str, list[GitRepository]] = {}
    for repo in prunable_repos:
        for remote in repo.list_remotes():
            try:
                url_repos_map[remote.url].append(repo)
            except KeyError:
                url_repos_map[remote.url] = [repo]

    for remote_repo in _list_remote_repos(
        options.provider,
        options.hostname,
        options.owner
    ):
        if not matches_globs(remote_repo.path, options.filters):
            continue

        repos = url_repos_map.get(remote_repo.url)
        if repos is None:
            new_repos.append(remote_repo)
        else:
            for repo in repos:
                existing_repos.add(repo)
                try:
                    prunable_repos.remove(repo)
                except KeyError:
                    log.debug("Repository '%s' already found", repo.path)
                    pass

    return new_repos, existing_repos, prunable_repos


def _list_remote_repos(
    provider: RemoteProvider,
    hostname: str | None,
    owner: str,
) -> Iterable[RemoteRepository]:
    if provider == RemoteProvider.GITHUB:
        return github_list_repos(owner, hostname=hostname)

    raise ValueError("Unsupported provider: " + provider)


def _find_local_repos(
    workspace: Path,
    provider: RemoteProvider,
    hostname: str | None,
    owner: str,
    path_template: str,
):
    path_pattern = path_template.format(owner=owner, name="*")
    path = PurePath(path_pattern)

    if hostname:
        expected_hostname = hostname
    elif provider == RemoteProvider.GITHUB:
        expected_hostname = GH_HOSTNAME
    else:
        raise ValueError("Unsupported provider: " + provider)

    found_repos = find_repos(workspace, FindOptions(
        depth=len(path.parts),
        hidden=any(p.startswith(".") for p in path.parts),
        filters=[path_pattern],
    ))

    local_repos: set[GitRepository] = set()
    for repo in found_repos:
        for remote in repo.list_remotes():
            url = urlparse(remote.url)
            remote_path = PurePosixPath(url.path.removeprefix("/"))
            remote_owner = str(remote_path.parent)

            if expected_hostname == url.netloc and owner == remote_owner:
                local_repos.add(repo)
                break

    return local_repos


def _resolve_clone_path(
    workspace: Path,
    repo: RemoteRepository,
    path_template: str,
):
    clone_path = Path(path_template.format(
        owner=repo.owner,
        name=repo.name,
    ))

    if not clone_path.is_absolute():
        clone_path = workspace / clone_path

    try:
        clone_path = clone_path.resolve()
    except RuntimeError as exc:
        raise GrmException(
            "Failed to resolve clone path of '{}': '{}'".format(
                repo.url,
                clone_path,
            )
        ) from exc

    return clone_path


def _resolve_archive_path(
    repo: GitRepository,
    path_template: str | None,
    owner: str,
    now: datetime,
) -> Path:
    if not path_template:
        raise ValueError("'archive' cannot be empty")

    archive_path = Path(path_template.format(
        owner=owner,
        name=repo.name,
        timestamp=str(now.timestamp()),
    )).expanduser()

    if not archive_path.is_absolute():
        archive_path = repo.path / archive_path

    try:
        archive_path = archive_path.resolve()
    except RuntimeError as exc:
        raise GrmException(
            "Failed to resolve archive path '{}': '{}'".format(
                repo.path,
                archive_path,
            )
        ) from exc

    try:
        if not archive_path.exists():
            return archive_path
    except NotADirectoryError:
        # parent directory doesn't exist yet -- which is fine since
        # it will be created when we actually archive the repository
        pass

    # name already taken -- append current epoch (millis)
    archive_path = archive_path.with_name(
        f"{archive_path.name}_{int(now.timestamp() * 1000)}"
    )

    if archive_path.exists():
        raise GrmException(
            "Cannot archive '{}' to '{}'. Path already exists".format(
                repo.path,
                archive_path,
            )
        )

    return archive_path


def _log_plan(
    workspace: Path,
    clone_jobs: Collection[tuple[Path, RemoteRepository]],
    existing_repos: Collection[GitRepository],
    prunable_repos: Collection[GitRepository],
    archive_jobs: list[tuple[Path, GitRepository]],
):
    if prunable_repos and log.isEnabledFor(logging.WARNING):
        prunable_paths = [
            str(r.path.relative_to(workspace))
            for r in prunable_repos
        ]
        prunable_paths.sort()

        log.warning(
            "Found %d prunable repositor%s (will be DELETED): \n- %s",
            len(prunable_repos),
            "y" if len(prunable_repos) <= 1 else "ies",
            "\n- ".join(prunable_paths),
        )

    if archive_jobs and log.isEnabledFor(logging.WARNING):
        archive_paths = [
            f"{r.path.relative_to(workspace)} -> {p}"
            for p, r in archive_jobs
        ]
        archive_paths.sort()

        log.warning(
            "Found %d archivable repositor%s (will be archived): \n- %s",
            len(archive_jobs),
            "y" if len(archive_jobs) else "ies",
            "\n- ".join(archive_paths)
        )

    if clone_jobs:
        if log.isEnabledFor(logging.INFO):
            jobs = [
                f"{repo.url} ({clone_path.relative_to(workspace)})"
                for clone_path, repo in clone_jobs
            ]
            jobs.sort()

            log.info(
                "Found %d new repositor%s (will be cloned): \n- %s",
                len(clone_jobs),
                "y" if len(clone_jobs) <= 1 else "ies",
                "\n- ".join(jobs)
            )
    else:
        log.info("No new repositories to clone.")

    if existing_repos:
        if log.isEnabledFor(logging.DEBUG):
            existing_paths = [str(r.path) for r in existing_repos]
            existing_paths.sort()

            log.debug(
                "Found %d existing repositor%s (already cloned): \n- %s",
                len(existing_repos),
                "y" if len(existing_repos) <= 1 else "ies",
                "\n- ".join(existing_paths),
            )
        else:
            log.info(
                "Found %d existing repositor%s (already cloned)",
                len(existing_repos),
                "y" if len(existing_repos) <= 1 else "ies",
            )


def _log_results(
    workspace: Path,
    clone_success: Collection[GitRepository],
    clone_failed: Collection[RemoteRepository],
    prune_success: Collection[GitRepository],
    prune_failed: Collection[GitRepository],
    archive_success: Collection[tuple[Path, GitRepository]],
    archive_failed: Collection[GitRepository],
):
    log.info("Clone complete.\n")

    if prune_success and log.isEnabledFor(logging.WARNING):
        results = [
            str(repo.path.relative_to(workspace))
            for repo in prune_success
        ]
        results.sort()

        log.warning(
            "Pruned %d respositor%s: \n- %s\n",
            len(prune_success),
            "y" if len(prune_success) <= 1 else "ies",
            "\n- ".join(results)
        )

    if archive_success and log.isEnabledFor(logging.WARNING):
        results = [
            f"'{repo.path.relative_to(workspace)}' -> '{archive_path}'"
            for archive_path, repo in archive_success
        ]
        results.sort()

        log.warning(
            "Archived %d repositor%s: \n- %s\n",
            len(archive_success),
            "y" if len(archive_success) <= 1 else "ies",
            "\n- ".join(results)
        )

    if clone_success and log.isEnabledFor(logging.INFO):
        results = [
            str(repo.path.relative_to(workspace))
            for repo in clone_success
        ]
        results.sort()

        log.info(
            "Cloned %d repositor%s: \n- %s\n",
            len(clone_success),
            "y" if len(clone_success) <= 1 else "ies",
            "\n- ".join(results),
        )

    if prune_failed and log.isEnabledFor(logging.ERROR):
        results = [
            str(repo.path.relative_to(workspace))
            for repo in prune_failed
        ]
        results.sort()

        log.error(
            "Failed to prune %d respositor%s: \n- %s\n",
            len(prune_failed),
            "y" if len(prune_failed) <= 1 else "ies",
            "\n- ".join(results)
        )

    if archive_failed and log.isEnabledFor(logging.ERROR):
        results = [
            str(repo.path.relative_to(workspace))
            for repo in archive_failed
        ]
        results.sort()

        log.error(
            "Failed to archive %d respositor%s: \n- %s\n",
            len(archive_failed),
            "y" if len(archive_failed) <= 1 else "ies",
            "\n- ".join(results)
        )

    if clone_failed and log.isEnabledFor(logging.ERROR):
        results = [repo.url for repo in clone_failed]
        results.sort()

        log.error(
            "Failed to clone %d repositor%s: \n- %s\n",
            len(clone_failed),
            "y" if len(clone_failed) <= 1 else "ies",
            "\n- ".join(results)
        )
