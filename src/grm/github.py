import logging
import json
import subprocess
from typing import Generator
import typer

from grm.util import GrmException, RemoteRepository, run_cmd


ERR_LIST_REPOS = "Failed to list repositories owned by '{}'. {}"

GH_HOSTNAME = "github.com"
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
    hostname: str | None = None
) -> Generator[RemoteRepository, None, None]:
    log.info("Listing GitHub repositories of '%s'...", owner)

    page = 1
    total = 0
    is_org = True

    while True:
        if is_org:
            repos = _gh_list_repos(org=owner, page=page, hostname=hostname)
        else:
            repos = _gh_list_repos(user=owner, page=page, hostname=hostname)

        if page == 1 and len(repos) == 0:
            if is_org:
                is_org = False
                continue
            else:
                raise GeneratorExit()

        log.debug(
            "GitHub list_repos owner='%s', page=%d (%d-%d)",
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

            yield RemoteRepository(
                provider="github",
                url=clone_url,
            )

        page += 1

        if len(repos) < PER_PAGE:
            break

    log.debug("Found %d GitHub repositories owned by '%s'", total, owner)


def _gh_list_repos(
    *,
    user: str = "",
    org: str = "",
    page: int = 1,
    hostname: str | None
) -> list:
    if user:
        repos = _gh_api(
            f"/users/{user}/repos?page={page}&per_page={PER_PAGE}",
            hostname=hostname,
        )
    elif org:
        repos = _gh_api(
            f"/orgs/{org}/repos?page={page}&per_page={PER_PAGE}",
            hostname=hostname,
        )
    else:
        repos = []

    if type(repos) is not list:
        raise GitHubException(ERR_LIST_REPOS.format(
            "Invalid GitHub API response (expected 'list' but got "
            f"'{type(repos).__name__}')"
        ))

    return repos


def _gh_api(endpoint: str, hostname: str | None):
    args = [
        "gh",
        "api",
        "-H", f"Accept: {GH_API_ACCEPT_JSON}",
        "-H", f"X-GitHub-Api-Version: {GH_API_VERSION}",
        endpoint,
    ]
    if hostname:
        args.append("--hostname")
        args.append(hostname)
    try:
        result = run_cmd(None, args)
    except FileNotFoundError:
        raise GitHubException(
            "GitHub CLI (gh) not found. Check that GitHub CLI is "
            "installed and is available"
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
