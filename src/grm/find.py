from collections.abc import Generator
import logging
import os
from pathlib import Path
from stat import S_ISREG, S_ISDIR
from typing import Annotated
import typer

from grm.config import FindOptions
from grm.git import GitRepository
from grm.util import matches_globs


app = typer.Typer()
log = logging.getLogger(__name__)


@app.command("find", help="Recursively search for local git repositories")
def cmd_find(
    depth: Annotated[int, typer.Option(
        "-d", "--depth",
        help="Maximum search recursion depth (0 for no limit)",
    )] = 0,
    hidden: Annotated[bool, typer.Option(
        "--hidden",
        help="Include hidden files (starting with '.') in search",
    )] = False,
    filters: Annotated[list[str], typer.Option(
        "-g", "--glob",
        help="Repository path filter (relative from search root path)",
    )] = [],
    sort: Annotated[bool, typer.Option(
        "--sort",
        help="Sort result output",
    )] = False,
):
    repos = find_repos(Path.cwd(), FindOptions(depth, hidden, filters))
    if sort:
        repos = list(repos)
        repos.sort(key=lambda r: r.path)

    for repo in repos:
        print(repo.path)


@app.command("ls", help="List git repositories in given directory")
def cmd_ls(
    path: Annotated[Path, typer.Argument(
        default_factory=Path.cwd,
        help="Repository search root path",
    )],
    hidden: Annotated[bool, typer.Option(
        "--hidden",
        help="Include hidden files (starting with '.') in search",
    )] = False,
    sort: Annotated[bool, typer.Option(
        "--sort",
        help="Sort result output",
    )] = False,
):
    repos = find_repos(path, FindOptions(depth=1, hidden=hidden))
    if sort:
        repos = list(repos)
        repos.sort(key=lambda r: r.path)

    for repo in repos:
        print(repo.path)


def find_repos(path: Path, opts: FindOptions) -> set[GitRepository]:
    log.debug("Searching for repositories in '%s'...", path)
    dirs: list[Path] = [path]
    repos: set[GitRepository] = set()

    while True:
        try:
            dirpath = dirs.pop()
        except IndexError:
            break

        relpath = dirpath.relative_to(path)
        if opts.depth > 0 and len(relpath.parts) > opts.depth:
            continue

        if not opts.hidden and dirpath.name.startswith("."):
            continue

        try:
            mode = _get_mode(dirpath / ".git")
        except FileNotFoundError:
            dirs.extend(_find_subdirs(dirpath))
            continue

        if opts.filters and not matches_globs(str(relpath), opts.filters):
            continue

        if S_ISREG(mode):  # linked worktree
            repos.add(GitRepository(dirpath).resolve())
        elif S_ISDIR(mode):  # main worktree
            repos.add(GitRepository(dirpath))
        else:
            continue

    if repos:
        repositories = "repository" if len(repos) == 1 else "repositories"
        log.debug("Found %d %s in '%s'", len(repos), repositories, path)
    else:
        log.debug("No repositories found in '%s'", path)

    return repos


def _find_subdirs(path: Path) -> Generator[Path, None, None]:
    try:
        with os.scandir(path) as entries:
            for e in entries:
                if e.is_dir(follow_symlinks=False):
                    yield Path(e)
    except OSError as exc:
        log.error(
            "ERROR: Failed to search '%s'. %s",
            path,
            exc,
            exc_info=log.isEnabledFor(logging.DEBUG),
        )


def _get_mode(path: Path) -> int:
    try:
        return path.stat().st_mode
    except FileNotFoundError:
        raise
    except NotADirectoryError:
        pass
    except PermissionError:
        log.warning("No permission to read '%s'", path)
    except TimeoutError:
        log.warning("Timeout while reading '%s'", path)
    except OSError as exc:
        log.error(
            "ERROR: Failed to search '%s'. %s",
            path,
            exc,
            exc_info=log.isEnabledFor(logging.DEBUG)
        )

    return 0
