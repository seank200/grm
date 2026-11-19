from collections.abc import Collection
import logging
from pathlib import Path

from grm.config import FetchOptions
from grm.git import GitException, GitRepository


log = logging.getLogger(__name__)


def fetch_repos(
    workspace: Path,
    repos: Collection[GitRepository],
    options: FetchOptions
) -> list[GitRepository]:
    if not repos or not options.enabled:
        return []

    log.info(
        "Fetching %d repositor%s...",
        len(repos),
        "y" if len(repos) <= 1 else "ies",
    )

    success: list[GitRepository] = []
    failed: list[GitRepository] = []

    for repo in repos:
        log.info("Fetching '%s'", repo.path.relative_to(workspace))

        try:
            proc = repo.fetch()
        except GitException as exc:
            failed.append(repo)
            log.error("ERROR: %s. %s", exc, exc.__cause__ or "")
            continue

        success.append(repo)

        output = proc.stderr.rstrip("\n")
        if output:
            log.info(
                "Fetched '%s'. %s",
                repo.path.relative_to(workspace),
                output,
            )
        else:
            log.debug("Fetched '%s'", repo.path)

    log.info("Fetch complete.\n")
    _log_results(workspace, success, failed)

    return success


def _log_results(
    workspace: Path,
    success: Collection[GitRepository],
    failed: Collection[GitRepository],
):
    if success and log.isEnabledFor(logging.INFO):
        results = [str(repo.path.relative_to(workspace)) for repo in success]
        results.sort()

        log.info(
            "Fetched %d repositor%s: \n- %s\n",
            len(success),
            "y" if len(success) <= 1 else "ies",
            "\n- ".join(results)
        )

    if failed and log.isEnabledFor(logging.ERROR):
        results = [str(repo.path.relative_to(workspace)) for repo in failed]
        results.sort()

        log.error(
            "Failed to fetch %d repositor%s: \n- %s\n",
            len(failed),
            "y" if len(failed) <= 1 else "ies",
            "\n- ".join(results)
        )
