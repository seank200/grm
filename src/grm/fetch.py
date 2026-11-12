from collections.abc import Collection
import logging
from pathlib import Path
import typer
from typing import Annotated

from grm.config import FetchOptions, FindOptions
from grm.find import find_repos
from grm.git import GitException, GitRepository


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("fetch", help="Fetch changes from remote repositories")
def cmd_fetch(
    filters: Annotated[list[str], typer.Option(
        "-g", "--glob",
        help="Filter repositories by local path (relative to cwd)",
    )] = [],
    all: Annotated[bool, typer.Option(
        "--all",
        help="Fetch all remotes. See git-fetch(1)."
    )] = False,
    prune: Annotated[bool, typer.Option(
        "-p", "--prune",
        help="Before fetching, remove any remote-tracking references "
             "that no longer exist on the remote. See git-fetch(1).",
    )] = False,
    no_tags: Annotated[bool, typer.Option(
        "-n", "--no-tags",
        help="By default, tags that point at objects that are "
             "downloaded from the remote repository are fetched and "
             "stored locally. This option disables this automatic "
             "tag following. See git-fetch(1).",
    )] = False,
    tags: Annotated[bool, typer.Option(
        "-t", "--tags",
        help="Fetch all tags from the remote (i.e., fetch remote tags "
             "refs/tags/* into local tags with the same name), in "
             "addition to whatever else would otherwise be fetched."
             "See git-fetch(1)."
    )] = False,
    prune_tags: Annotated[bool, typer.Option(
        "-P", "--prune-tags",
        help="Before fetching, remove any local tags that no longer "
             "exist on the remote if --prune is enabled. "
             "See git-fetch(1).",
    )] = False,
):
    cwd = Path.cwd()
    repos = find_repos(cwd, FindOptions(filters=filters))

    if tags:
        _tags = True
    elif no_tags:
        _tags = False
    else:
        _tags = None

    fetch_repos(cwd, repos, FetchOptions(
        all=all,
        prune=prune,
        tags=_tags,
        prune_tags=prune_tags,
    ))


def fetch_repos(
    workspace: Path,
    repos: Collection[GitRepository],
    opts: FetchOptions
) -> list[GitRepository]:
    if not repos:
        return []

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    log.info(
        "Fetching %d %s...",
        len(repos),
        "repository" if len(repos) <= 1 else "repositories",
    )
    for repo in repos:
        rel_path = repo.path.relative_to(workspace)
        log.info("Fetching '%s'", rel_path)
        try:
            proc = repo.fetch(
                all=opts.all,
                prune=opts.prune,
                tags=opts.tags,
                prune_tags=opts.prune_tags,
            )
        except GitException as exc:
            log.error("ERROR: %s", exc)
            failed.append(repo)
            continue

        success.append(repo)

        output = proc.stderr.rstrip("\n")
        if output:
            log.info("Fetched '%s'. \n%s", rel_path, output)
        else:
            log.debug("Fetched '%s'", rel_path)

    _log_results(workspace, success, failed)

    return success


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
            "Fetched %d/%d %s: %s",
            len(success),
            len(success) + len(failed),
            "repository" if len(success) <= 1 else "repositories",
            ", ".join(success_paths),
        )

    if failed:
        if log.isEnabledFor(logging.ERROR):
            failed_paths = [
                str(repo.path.relative_to(workspace))
                for repo in failed
            ]
            failed_paths.sort()

            log.error(
                "ERROR: Failed to fetch %d/%d %s: \n - %s",
                len(failed),
                len(success) + len(failed),
                "repository" if len(failed) <= 1 else "repositories",
                "\n - ".join(failed_paths),
            )
