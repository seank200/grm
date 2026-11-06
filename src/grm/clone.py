from collections.abc import Collection, Iterable
import logging
from pathlib import Path
import typer
from typing import Annotated

from grm import github
from grm.config import CloneOptions
from grm.find import find_repos
from grm.git import GitException, GitRepository
from grm.util import InvalidConfigError, RemoteRepository, matches_globs


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("clone")
def cmd_clone(
    owner: Annotated[str, typer.Argument(
        help="Remote provider account or organization(group) name",
    )],
    globs: Annotated[list[str], typer.Option(
        "-g", "--glob",
        default_factory=list,
        help="UNIX-style glob filter (clone URL path, case-insensitive)."
             "Prefix with '!' to exclude matching repositories"
    )],
    path: Annotated[str, typer.Option(
        "-p", "--path",
        help="Path template to use for cloned repositories "
             "(supported fields: 'owner', 'name')",
    )] = "{name}",
    provider: Annotated[str, typer.Option(
        "--provider",
        help="Remote repository provider (possible values: 'github')",
    )] = "github",
    prune: Annotated[bool, typer.Option(
        "--prune",
        help="Permenantly delete repositories that no longer exist "
             "in remote (mutually exclusive with '--archive')"
    )] = False,
    archive: Annotated[bool, typer.Option(
        "--archive",
        help="Move repositories that no longer exist in remote to "
             "the archive directory (mutually exclusive with '--prune')"
    )] = False,
):
    opts = CloneOptions(
        owner=owner,
        path=path,
        provider=provider,
        prune=prune,
        archive=archive,
        globs=globs,
    )

    clone_repos(
        Path.cwd(),
        opts,
        existing_repos=find_repos(Path.cwd())
    )


def clone_repos(
    path: Path,
    opts: CloneOptions,
    *,
    existing_repos: Collection[GitRepository] = [],
) -> list[GitRepository]:
    log.info("Cloning GitHub repositories (%s)...", opts.owner)

    _existing_repos: dict[str, GitRepository] = {
        remote.url: repo
        for repo in existing_repos
        for remote in repo.list_remotes()
    }
    failed_urls = []
    skipped_repos: list[GitRepository] = []
    cloned_repos: list[GitRepository] = []

    for remote_repo in _list_remote_repos(opts):
        existing_repo = _existing_repos.get(remote_repo.url)
        if existing_repo:
            skipped_repos.append(existing_repo)
            continue

        if opts.globs \
                and not matches_globs(str(remote_repo.path), opts.globs):
            log.debug("Not cloning '%s' (filtered)", remote_repo.url)
            continue

        repo_path = path / opts.path.format(
            owner=remote_repo.owner,
            name=remote_repo.name
        )
        if repo_path.exists():
            log.error(
                "Failed to clone '%s' (path already exists: '%s')",
                remote_repo.url,
                repo_path,
            )
            failed_urls.append(remote_repo.url)
            continue

        try:
            repo = GitRepository.clone(remote_repo.url, repo_path)
        except GitException as exc:
            failed_urls.append(remote_repo.url)
            log.error("ERROR: %s", exc)
            continue

        cloned_repos.append(repo)

    _log_clone_results(opts, cloned_repos, skipped_repos, failed_urls)
    return cloned_repos


def _list_remote_repos(opts: CloneOptions) -> Iterable[RemoteRepository]:
    if opts.provider == "github":
        return github.list_repos(opts.owner)

    raise InvalidConfigError(
        f"Unsupported provider '{opts.provider}'",
        field="clone.provider",
    )


def _log_clone_results(
    opts: CloneOptions,
    cloned_repos: list[GitRepository],
    skipped_repos: list[GitRepository],
    failed_urls: list[str],
):
    if cloned_repos and log.isEnabledFor(logging.INFO):
        log.debug(
            "New repositories (%d): %s",
            len(cloned_repos),
            ", ".join(r.name for r in cloned_repos)
        )

    if skipped_repos and log.isEnabledFor(logging.INFO):
        log.debug(
            "Already cloned (%d): %s",
            len(skipped_repos),
            ", ".join(r.name for r in skipped_repos),
        )

    if failed_urls and log.isEnabledFor(logging.WARNING):
        log.warning(
            "Clone failed (%d): %s%s",
            len(failed_urls),
            "\n - ",
            "\n - ".join(failed_urls),
        )

    log.info(
        "Cloned GitHub repositories (%s): %d success, %d failed "
        "(%d already cloned)",
        opts.owner,
        len(cloned_repos),
        len(failed_urls),
        len(skipped_repos),
    )
