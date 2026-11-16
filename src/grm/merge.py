from collections.abc import Collection
import logging
from pathlib import Path
from typing import Annotated
import typer

from grm.config import MergeOptions
from grm.find import find_repos, FindOptions
from grm.git import GitRepository, GitWorktree
from grm.util import GrmException, InvalidArgsError


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("merge", help="Merge upstream changes into the current branch")
def cmd_merge(
    ff: Annotated[bool, typer.Option(
        "--ff",
        help="When possible resovle the merge as a fast-forward, "
             "and when not possible, create a merge commit. "
    )] = False,
    no_ff: Annotated[bool, typer.Option(
        help="Create a merge commit in all cases even when "
             "the merge could instead be resolved as a fast-forward.",
    )] = False,
    ff_only: Annotated[bool, typer.Option(
        "--ff-only",
        help="Resolve the merge as a fast-forward when possible. When "
             "not possible, refuse to merge",
    )] = False,
):
    if int(ff) + int(no_ff) + int(ff_only) > 1:
        raise InvalidArgsError(
            "Multiple merge strategies selected -- choose one of: "
            "'--ff', '--no-ff', '--ff-only'",
        )

    if ff:
        _ff = True
    elif no_ff:
        _ff = False
    else:
        _ff = None

    cwd = Path.cwd()
    repos = find_repos(cwd, FindOptions(depth=0, hidden=False))
    merge_repos(cwd, repos, MergeOptions(ff=_ff, ff_only=ff_only))


def merge_repos(
    workspace: Path,
    repos: Collection[GitRepository],
    options: MergeOptions,
) -> list[GitRepository]:
    log.info(
        "Merging upstream changes of %d %s...",
        len(repos),
        "repository" if len(repos) <= 1 else "repositories",
    )

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    for repo in repos:
        for worktree in repo.list_worktrees():
            try:
                _merge_repo(workspace, repo, worktree, options)
            except GrmException as exc:
                log.error(
                    "ERROR: Failed to merge upstream changes of '%s'. %s",
                    worktree.path.relative_to(workspace),
                    exc,
                )
                failed.append(repo)
                continue

        success.append(repo)

    _log_results(workspace, success, failed)
    return success


def _merge_repo(
    workspace: Path,
    repo: GitRepository,
    worktree: GitWorktree,
    options: MergeOptions
):
    branch = repo.current_branch()
    if branch is None:
        raise GrmException("HEAD is detached")
    if branch.upstream is None:
        raise GrmException(f"'{branch.name}' has no remote-tracking branch")

    proc = repo.merge(
        branch.upstream,
        ff=options.ff,
        ff_only=options.ff_only,
        worktree=worktree,
    )

    log.info(
        "Merged '%s' (%s..%s). %s",
        worktree.path.relative_to(workspace),
        branch.name_short,
        branch.upstream_short,
        proc.stdout.rstrip("\n"),
    )


def _log_results(
    workspace: Path,
    success: list[GitRepository],
    failed: list[GitRepository]
):
    if success and log.isEnabledFor(logging.INFO):
        success_paths = [
            str(repo.path.relative_to(workspace))
            for repo in success
        ]
        success_paths.sort()

        log.info(
            "Merged upstream changes of %d/%d %s: %s",
            len(success),
            len(success) + len(failed),
            "repository" if len(success) <= 1 else "repositories",
            ", ".join(success_paths),
        )

    if failed and log.isEnabledFor(logging.ERROR):
        failed_paths = [
            str(repo.path.relative_to(workspace))
            for repo in failed
        ]
        failed_paths.sort()

        log.error(
            "ERROR: Failed to merge upstream changes of %d/%d %s: \n - %s",
            len(failed),
            len(success) + len(failed),
            "repository" if len(failed) <= 1 else "repositories",
            "\n - ".join(failed_paths),
        )
