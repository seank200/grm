from collections.abc import Collection
import logging
from pathlib import Path

from grm.config import MergeOptions
from grm.git import GitRepository, GitWorktree
from grm.util import GrmException, TqdmWrapper


log = logging.getLogger(__name__)


def merge_repos(
    workspace: Path,
    repos: Collection[GitRepository],
    options: MergeOptions,
) -> list[GitRepository]:
    if not options.enabled:
        return []

    log.info(
        "Merging %d repositor%s...",
        len(repos),
        "y" if len(repos) <= 1 else "ies",
    )

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    with TqdmWrapper(desc="Merging", total=len(repos)) as bar:
        for repo in repos:
            is_success = True
            for worktree in repo.list_worktrees():
                try:
                    _merge_upstream(workspace, repo, worktree, options)
                except GrmException as exc:
                    is_success = False
                    log.error(
                        "ERROR: Failed to merge '%s'. %s",
                        repo.path.relative_to(workspace),
                        exc,
                    )
                    break

            if is_success:
                success.append(repo)
            else:
                failed.append(repo)
            bar.update(1)

    log.info("Merge complete.\n")
    _log_results(workspace, success, failed)

    return success


def _merge_upstream(
    workspace: Path,
    repo: GitRepository,
    worktree: GitWorktree,
    options: MergeOptions,
):
    log.debug("Merging '%s'...", worktree.path)

    branch = repo.current_branch(worktree=worktree)
    if branch is None:
        raise GrmException("HEAD is detached")

    if branch.upstream is None:
        raise GrmException("'{}' has no remote-tracking branch".format(
            branch.name_short,
        ))

    proc = repo.merge(branch.upstream, ff=options.ff, ff_only=options.ff_only)

    if worktree.path.is_relative_to(workspace):
        worktree_path = worktree.path.relative_to(workspace)
    else:
        worktree_path = worktree.path
    log.info(
        "Merged '%s' (%s..%s). %s",
        worktree_path,
        branch.name_short,
        branch.upstream_short,
        proc.stdout.rstrip("\n"),
    )


def _log_results(
    workspace: Path,
    success: Collection[GitRepository],
    failed: Collection[GitRepository],
):
    if success and log.isEnabledFor(logging.INFO):
        results = [str(repo.path.relative_to(workspace)) for repo in success]
        results.sort()

        log.info(
            "Merged %d repositor%s: \n- %s\n",
            len(success),
            "y" if len(success) <= 1 else "ies",
            "\n- ".join(results),
        )

    if failed and log.isEnabledFor(logging.ERROR):
        results = [str(repo.path.relative_to(workspace)) for repo in failed]
        results.sort()

        log.error(
            "Failed to merge %d repositor%s: \n- %s\n",
            len(failed),
            "y" if len(failed) <= 1 else "ies",
            "\n- ".join(results),
        )
