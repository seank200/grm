import logging
import json
import subprocess
from typing import Generator
import typer

from grm.util import GrmException, RemoteRepository, matches_globs, run_cmd


ERR_LIST_REPOS = "Failed to list repositories owned by '{}'. {}"

GH_API_ACCEPT_JSON = "application/vnd.github+json"
GH_API_VERSION = "2026-03-10"

PER_PAGE = 64


class GitHubException(GrmException):
    """GitHub CLI (gh) finished with an unexpected result"""
    ...


app = typer.Typer()
log = logging.getLogger(__name__)


def list_repos(
    owner: str,
    *,
    globs: list[str]
) -> Generator[RemoteRepository, None, None]:
    log.info("Listing GitHub repositories owned by '%s'...", owner)

    page = 1
    matched = 0
    total = 0
    is_org = True

    while True:
        if is_org:
            repos = _gh_list_repos(org=owner, page=page)
        else:
            repos = _gh_list_repos(user=owner, page=page)

        if page == 1 and len(repos) == 0:
            if is_org:
                is_org = False
                continue
            else:
                raise GeneratorExit()

        log.debug(
            "Listed GitHub repositories owned by '%s' (page %d, %d-%d)",
            owner,
            page,
            PER_PAGE * (page-1),
            PER_PAGE * (page-1) + len(repos) - 1,
        )

        for repo in repos:
            total += 1
            try:
                clone_url = repo["clone_url"]
            except KeyError as exc:
                raise GitHubException(ERR_LIST_REPOS.format(
                    f"Invalid GitHub API response (missing property '{exc}')"
                ))

            remote_repo = RemoteRepository(
                provider="github",
                url=clone_url,
            )
            if globs:
                remote_path = remote_repo.path().removeprefix("/")
                if not matches_globs(remote_path, globs):
                    continue

            matched += 1
            yield remote_repo

        page += 1

        if len(repos) < PER_PAGE:
            break

    if globs:
        log.debug(
            "Matched %d/%d GitHub repositories owned by '%s'",
            matched,
            total,
            owner
        )
    else:
        log.debug("Found %d GitHub repositories owned by '%s'", total, owner)


def _gh_list_repos(*, user: str = "", org: str = "", page: int = 1) -> list:
    if user:
        repos = _gh_api(f"/users/{user}/repos?page={page}&per_page={PER_PAGE}")
    elif org:
        repos = _gh_api(f"/orgs/{org}/repos?page={page}&per_page={PER_PAGE}")
    else:
        repos = []

    if type(repos) is not list:
        raise GitHubException(ERR_LIST_REPOS.format(
            "Invalid GitHub API response (expected 'list' but got "
            f"'{type(repos).__name__}')"
        ))

    return repos


def _gh_api(endpoint: str):
    try:
        result = run_cmd(
            None,
            (
                "gh",
                "api",
                "-H", f"Accept: {GH_API_ACCEPT_JSON}",
                "-H", f"X-GitHub-Api-Version: {GH_API_VERSION}",
                endpoint
            )
        )
    except subprocess.CalledProcessError as exc:
        raise GitHubException(
            f"GitHub API error ({exc.returncode}). {exc.stderr}"
        )

    if result.stdout:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubException(
                "Invalid response from GitHub API (not a valid JSON)"
            ) from exc

    return None
