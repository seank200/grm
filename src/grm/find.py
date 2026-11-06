import logging
import os
from pathlib import Path
from stat import S_ISREG, S_ISDIR

from grm.git import GitRepository
from grm.util import GrmException, matches_globs


log = logging.getLogger(__name__)


def find_repos(
    path: Path,
    depth: int = 0,
    *,
    hidden: bool = False,
    globs: list[str] = [],
) -> list[GitRepository]:
    queue: list[Path] = []
    repos: set[GitRepository] = set()

    if path.is_dir():
        queue.append(path)

    while True:
        try:
            dir = queue.pop()
        except IndexError:
            break

        if depth > 0 and len(dir.relative_to(path).parts) > depth:
            continue

        try:
            gitfile_mode = (dir / ".git").stat().st_mode
        except FileNotFoundError:
            with os.scandir(dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if hidden or not entry.name.startswith("."):
                            queue.append(Path(entry.path))
            continue
        except PermissionError:
            log.warning("Not searching '%s' (no permissions)", dir)
            continue
        except OSError as exc:
            raise GrmException(f"Failed to search '{dir}'") from exc

        if globs and not matches_globs(str(dir.relative_to(path)), globs):
            log.debug("Ignoring '%s' (does not match pattern)", dir)
            continue

        if S_ISREG(gitfile_mode):
            repos.add(GitRepository(dir).resolve())
        elif S_ISDIR(gitfile_mode):
            repos.add(GitRepository(dir))
        else:
            log.warning("Ignoring '%s' ('.git' is not a file nor a directory)")

    log.debug("Found %d repositories in '%s'", len(repos), path)

    return [repo for repo in repos]
