from collections.abc import Iterable
import logging
from pathlib import Path
import typer
from typing import Annotated, Optional

from grm.config import (
    SyncOptions,
    WorktreeOptions,
    get_config,
    load_config,
)
from grm.clone import clone_repos
from grm.fetch import fetch_repos
from grm.find import find_repos
from grm.git import GitException, GitRepository, GitWorktree
from grm.merge import merge_repos


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("sync", help="Synchronize changes with remote")
def cmd_sync(
    config_file: Annotated[Optional[Path], typer.Option(
        "-f", "--filename",
        file_okay=True,
        help="Path to sync options file",
    )] = None,
):
    config = load_config(config_file) if config_file else get_config()

    for workspace in config.workspaces:
        sync_repos(workspace.path, workspace.sync)

    if config.workspaces:
        log.info(
            "Sync complete (%d workspace%s)",
            len(config.workspaces),
            "" if len(config.workspaces) <= 1 else "s",
        )
    else:
        log.warning("No workspaces configured")


def sync_repos(workspace: Path, options: SyncOptions):
    log.info("Syncing '%s'...", workspace)

    cloned_repos = clone_repos(workspace, options.clone)
    found_repos = find_repos(workspace, options.find)
    fetched_repos = fetch_repos(
        workspace,
        found_repos - cloned_repos,
        options.fetch
    )
    created_worktrees = create_worktrees(
        workspace,
        found_repos,
        options.worktrees
    )
    merged_repos = merge_repos(workspace, found_repos, options.merge)

    if log.isEnabledFor(logging.INFO):
        log_msg = "Synced '%s'"
        log_args: list = [workspace]

        summary: list[str] = []
        if cloned_repos:
            summary.append(f"{len(cloned_repos)} cloned")
        if fetched_repos:
            summary.append(f"{len(fetched_repos)} fetched")
        if merged_repos:
            summary.append(f"{len(merged_repos)} merged")
        if created_worktrees:
            summary.append(f"{len(created_worktrees)} worktrees created")

        if summary:
            log_msg += ": %s"
            log_args.append(", ".join(summary))

        log.info(log_msg, *log_args)


def create_worktrees(
    workspace: Path,
    repos: Iterable[GitRepository],
    options_list: list[WorktreeOptions]
) -> list[GitWorktree]:
    created_worktrees: list[GitWorktree] = []

    if not options_list:
        return created_worktrees

    for repo in repos:
        worktrees = repo.list_worktrees()
        worktree_paths = [w.path for w in worktrees]
        main_worktree = worktrees[0] if worktrees else None
        worktree_base_path = main_worktree.path if main_worktree else repo.path

        for options in options_list:
            worktree_sub_path = options.path_template.format(
                ref=options.ref,
                name=repo.name,
            )
            worktree_path = (worktree_base_path / worktree_sub_path).resolve()
            if worktree_path in worktree_paths:
                log.debug(
                    "Worktree '%s' -> '%s' (%s) already exists",
                    worktree_base_path,
                    worktree_path,
                    options.ref,
                )
                continue

            try:
                worktree = repo.create_worktree(worktree_path, options.ref)
                created_worktrees.append(worktree)
                log.info(
                    "Created worktree '%s' (%s) -> '%s'",
                    worktree_path,
                    options.ref,
                    worktree_base_path.relative_to(workspace),
                )
            except GitException as exc:
                log.error("ERROR: %s", exc)

    return created_worktrees

