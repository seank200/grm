import logging
from pathlib import Path
from typing import Annotated, Optional
import typer

from grm.clone import clone_repos
from grm.config import WorktreeOptions, get_config
from grm.fetch import fetch_repos
from grm.find import find_repos
from grm.git import GitRepository
from grm.merge import merge_repos


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("sync")
def cmd_sync(
    workspace_name: Annotated[Optional[str], typer.Argument(
        help="Name of the workspace to sync (sync all workspaces by default)"
    )] = None,
):
    config = get_config()

    for workspace in config.workspaces:
        if workspace_name and workspace.name != workspace_name:
            continue

        if workspace.name:
            log.info("Syncing '%s' (%s)...", workspace.name, workspace.path)
        else:
            log.info("Syncing '%s'...", workspace.path)

        cloned_repos = clone_repos(workspace.path, workspace.sync.clone)
        found_repos = find_repos(workspace.path, workspace.sync.find)

        existing_repos = found_repos - cloned_repos
        fetched_repos = fetch_repos(
            workspace.path,
            existing_repos,
            workspace.sync.fetch,
        )

        for repo in found_repos:
            sync_worktrees(workspace.path, repo, workspace.sync.worktrees)

        merged_repos = merge_repos(
            workspace.path,
            existing_repos,
            workspace.sync.merge,
        )

        log.info(
            "Synced %d repositor%s in '%s' (%d cloned, %d fetched, %d merged)",
            len(found_repos),
            "y" if len(found_repos) <= 1 else "ies",
            workspace.path,
            len(cloned_repos),
            len(fetched_repos),
            len(merged_repos),
        )

    log.info("Sync complete.")


def sync_worktrees(
    workspace: Path,
    repo: GitRepository,
    options_list: list[WorktreeOptions]
):
    existing_paths: set[Path] = set()
    for worktree in repo.list_worktrees():
        existing_paths.add(worktree.path.resolve())

    for options in options_list:
        worktree_path = Path(options.path.format(name=repo.name))
        if not worktree_path.is_absolute():
            worktree_path = repo.path / worktree_path
        worktree_path = worktree_path.resolve()

        if worktree_path in existing_paths:
            continue

        worktree = repo.create_worktree(worktree_path, options.ref)
        log.info(
            "Created worktree '%s' (%s) <- '%s'",
            worktree_path,
            options.ref,
            repo.path.relative_to(workspace),
        )
