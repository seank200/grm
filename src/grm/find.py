import logging
import os
import typer
from .context import console_out
from .exceptions import InvalidOptsError, SubprocessError
from .git import GitRepo, GitRemote
from .utils import OptionDef, num_workers, pl
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


@dataclass
class FindJob:
    path: Path
    depth: int
    

class FindOutput(Enum):
    NARROW = "narrow"
    WIDE = "wide"
    WIDER = "wider"
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    REMOTE = "remote"


@dataclass
class RepoFilter:
    """Repository search result filter options"""
    name: Optional[str] = None
    remote: Optional[str] = None
    dirty: Optional[bool] = None
    case_sensitive: bool = False

    def __post_init__(self):
        if not self.case_sensitive:
            self.name = self.name.lower() if self.name else self.name
            self.remote = self.remote.lower() if self.remote else self.remote

    def disabled(self) -> bool:
        return self.name is None and self.remote is None \
            and self.dirty is None
    
    def matches_name(self, repo: GitRepo) -> bool:
        return self.name is None \
            or self.name \
                in (repo.name if self.case_sensitive 
                    else repo.name.lower())
    
    def matches_remote(self, remote: GitRemote):
        return self.remote and remote.fetch and self.remote \
            in (remote.fetch if self.case_sensitive else remote.fetch.lower())

    def matches_remotes(self, repo: GitRepo) -> bool:
        if self.remote is None:
            return True
        
        for remote in repo.remotes.values():
            if self.matches_remote(remote):
                return True

        return False
    
    def matches_dirty(self, repo: GitRepo) -> bool:
        return self.dirty is None or self.dirty == repo.status.is_dirty()
    
    def matches(self, repo: GitRepo) -> bool:
        return self.matches_name(repo) and self.matches_remotes(repo) \
            and self.matches_dirty(repo)


@dataclass
class RepoJob:
    """Run selected repository commands to cache the results"""
    remote: bool = False
    status: bool = False


SEP = os.sep

SEARCH_PATH = OptionDef(
    "--path",
    "-p",
    envvar="SEARCH_PATH",
    help="Directory path to search for repositories"
)

SEARCH_DEPTH = OptionDef(
    "--depth",
    "-d",
    envvar="SEARCH_DEPTH",
    help="Maximum search depth"
)

FILTER_NAME = OptionDef(
    "--name",
    "-n",
    help="Filter by local repository name",
)

FILTER_REMOTE = OptionDef(
    "--remote-url",
    "-u",
    help="Filter by remote url"
)

FILTER_DIRTY = OptionDef(
    "--dirty/--clean",
    help="Filter by working tree status"
)

app = typer.Typer()
log = logging.getLogger(__name__)


def iter_repo_dirs(
    path: Path,
    depth: int,
) -> Iterator[GitRepo]:
    """Yields git repositories within the given path"""
    jobs: list[FindJob] = []

    if path.is_dir():
        jobs.append(FindJob(path, depth))

    while jobs:
        job = jobs.pop()
        try:
            if (job.path / ".git").is_dir():
                yield GitRepo(job.path)
            elif job.depth > 0:
                for child in job.path.iterdir():
                    if child.is_dir():
                        jobs.append(FindJob(child, job.depth-1))
        except PermissionError:
            log.error("No permission to search path: %s", job.path)
        except FileNotFoundError:
            log.error("Not searching non-existent path: %s", job.path)
        except NotADirectoryError:
            log.error("Not searching invalid path: %s", job.path)


def _worker_filter_repo(
    repo: GitRepo,
    filter: RepoFilter,
    job: Optional[RepoJob],
) -> Optional[GitRepo]:
    try:
        if not filter.matches(repo):
            return None
        if job is not None:
            if job.remote:
                repo.remotes
            if job.status:
                repo.status
        return repo
    except SubprocessError:
        log.error("Failed to inspect [cyan]%s[/]", repo.name)
        return None


def filter_repos(
    repos: Iterator[GitRepo],
    filter: RepoFilter,
    job: Optional[RepoJob] = None,
) -> list[GitRepo]:
    """Filter repository by given filter(s). Matches ALL filters when
    multiple filters are enabled. String filters match on a case-insensitive
    "contains" algorithm.
    """

    if filter.disabled():
        all_repos = list(repos)
        log.info("Found %d %s", len(all_repos), pl(all_repos, "repository"))
        return all_repos

    with ThreadPoolExecutor(max_workers=num_workers()) as executor:
        fs = (
            executor.submit(_worker_filter_repo, repo, filter, job)
            for repo in repos
        )

        try:
            done_fs = wait(fs, timeout=30.0).done
        except KeyboardInterrupt:
            executor.shutdown(cancel_futures=True)
            raise

    results: list[GitRepo] = []
    for f in done_fs:
        repo = f.result()
        if repo is not None:
            results.append(repo)

    log.info(
        "Matched %d out of %d %s",
        len(results),
        len(done_fs),
        pl(results, "repository")
    )
    
    return results


def find_repos(
    search_path: Path,
    search_depth: int,
    *,
    filter: Optional[RepoFilter] = None,
    job: Optional[RepoJob] = None,
) -> list[GitRepo]:
    log.info("Searching for repositories in %s", search_path)
    repos = filter_repos(
        iter_repo_dirs(search_path, search_depth),
        filter=filter if filter is not None else RepoFilter(),
        job=job,
    )
    return repos


def _output_remote(repos: list[GitRepo]):
    remote_urls_set: set[str] = set()
    for repo in repos:
        for remote in repo.remotes.values():
            if remote.fetch:
                remote_urls_set.add(remote.fetch)
    remote_urls: list[str] = list(remote_urls_set)
    remote_urls.sort()
    for url in remote_urls:
        remote = GitRemote("~", fetch=url)
        console_out.print(remote.render(show_name=False))


def _render_table(repos: list[GitRepo], output: FindOutput, render_root: Path) -> Table:
    repos.sort(key=lambda r: str(r.path))

    table = Table(
        box=None,
        pad_edge=True,
        header_style="bold underline",
    )
    table.add_column("#", justify="right")
    table.add_column("Local")
    table.add_column("Remote")

    for i, repo in enumerate(repos):
        row_num = str(i+1)
        repo_name = repo.render_path(
            None if output == FindOutput.WIDER else render_root
        )
        repo_remotes = repo.render_remotes(
            short=output == FindOutput.NARROW
        )
        table.add_row(row_num, repo_name, repo_remotes)

    return table


@app.command("find", help="Recursively search for git repositories in a directory")
def cmd_find(
    search_path: Annotated[Path, typer.Argument(
        envvar=SEARCH_PATH.envvar,
        default_factory=Path.cwd,
        show_default="Current working directory",
        help=SEARCH_PATH.help
    )],
    search_depth: Annotated[int, typer.Option(
        *SEARCH_DEPTH.options,
        envvar=SEARCH_DEPTH.envvar,
        help=SEARCH_DEPTH.help,
    )] = 1,
    filter_name: Annotated[Optional[str], typer.Option(
        *FILTER_NAME.options,
        help=FILTER_NAME.help,
    )] = None,
    filter_remote: Annotated[Optional[str], typer.Option(
        *FILTER_REMOTE.options,
        help=FILTER_REMOTE.help,
    )] = None,
    filter_dirty: Annotated[Optional[bool], typer.Option(
        *FILTER_DIRTY.options,
        help=FILTER_DIRTY.help,
    )] = None,
    output: Annotated[FindOutput, typer.Option(
        "--output",
        "-o",
        help="Output format"
    )] = FindOutput.NARROW,
):
    try:
        _search_path = search_path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        raise InvalidOptsError(f"Path '{search_path}' does not exist.")
    except NotADirectoryError:
        raise InvalidOptsError(f"Path '{search_path}' is invalid.")

    repos = find_repos(
        _search_path,
        search_depth,
        filter=RepoFilter(
            name=filter_name,
            remote=filter_remote,
            dirty=filter_dirty,
        ),
        job=RepoJob(remote=True)
    )

    if output == FindOutput.RELATIVE:
        repos.sort(key=lambda r: str(r.path))
        for repo in repos:
            console_out.print(repo.render_path(_search_path))
        return
    
    if output == FindOutput.ABSOLUTE:
        repos.sort(key=lambda r: str(r.path))
        for repo in repos:
            console_out.print(repo.render_path())
        return

    if output == FindOutput.REMOTE:
        _output_remote(repos)
        return

    # output is NARROW, WIDE, or WIDER
    console_out.print(_render_table(repos, output, _search_path))