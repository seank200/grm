import logging
from pathlib import Path
import typer
from typing import Annotated, Optional

from grm.config import (
    SyncOptions,
    get_config,
    load_config,
)
from grm.clone import clone_repos
from grm.fetch import fetch_repos
from grm.find import find_repos
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
            "Synchronized %d workspace%s",
            len(config.workspaces),
            "" if len(config.workspaces) <= 1 else "s",
        )
    else:
        log.warning("No workspaces configured")


def sync_repos(workspace: Path, options: SyncOptions):
    log.info("Syncing '%s'...", workspace)

    cloned_repos = clone_repos(workspace, options.clone)
    found_repos = find_repos(workspace, options.find)
    fetched_repos = fetch_repos(workspace, found_repos, options.fetch)
    merged_repos = merge_repos(workspace, fetched_repos, options.merge)

    if cloned_repos or merged_repos:
        if log.isEnabledFor(logging.INFO):
            n_success = len(cloned_repos) + len(merged_repos)
            cloned_paths = [
                str(repo.path.relative_to(workspace))
                for repo in cloned_repos + merged_repos
            ]
            cloned_paths.sort()

            log.info(
                "Synchronized %d %s in '%s': %s",
                n_success,
                "repository" if n_success <= 1 else "repositories",
                workspace,
                ", ".join(cloned_paths)
            )
    else:
        log.warning("Nothing to sync in '%s'", workspace)
