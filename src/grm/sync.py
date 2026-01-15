import logging
import subprocess
import typer
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional, Union
from .config import get_config, get_console
from .find import find_repos, Matcher
from .git import GitRepo
from .utils import max_threads


@dataclass
class FetchOptions:
    enabled: bool
    all: bool
    tags: bool
    prune: bool
    prune_tags: bool
    refetch: bool


@dataclass
class PushOptions:
    enabled: bool


@dataclass
class MergeOptions:
    enabled: bool
    ff: Optional[bool]
    ff_only: Optional[bool]
    message: Optional[str]
    log: Optional[int]


@dataclass
class SyncOptions:
    fetch: FetchOptions
    push: PushOptions
    merge: MergeOptions
    bail: bool
    quiet: bool
    verbose: bool


@dataclass
class SyncState:
    aborted: bool = False


@dataclass
class SyncResult:
    repo: GitRepo
    fetch: Optional[bool] = None
    push: Optional[bool] = None
    merge: Optional[bool] = None
    error: Optional[str] = None



app = typer.Typer()
log = logging.getLogger(__name__)


def _sync_worker(repo: GitRepo, options: SyncOptions, state: SyncState) -> SyncResult:
    if state.aborted:
        return SyncResult(repo, error="Aborted")
    
    result = SyncResult(repo)
    
    status = repo.status()

    if status.operation:
        result.error = f"{status.operation.value} in progress ({status.unmerged} unmerged)"
        return result

    if status.head.branch is None:
        result.error = "HEAD is detached"
        return result
    
    if status.head.branch.upstream is None and not options.fetch.all:
        return SyncResult(repo, error="No remote-tracking branch configured")
    
    try:
        repo.fetch(
            all=options.fetch.all,
            prune=options.fetch.prune,
            prune_tags=options.fetch.prune_tags,
            refetch=options.fetch.refetch,
            tags=options.fetch.tags,
            quiet=options.quiet,
            verbose=options.verbose,
        )
        
        result.fetch = True
    except subprocess.CalledProcessError as e:
        result.fetch = False
        result.error = f"git-fetch ({e.returncode})"
        return result
    
    status = repo.status()
    
    if status.ahead > 0 and status.behind > 0:
        result.error = "Histories diverged"
        return result
    
    if status.ahead > 0:
        if options.push.enabled:
            try:
                repo.push()

                result.push = True
            except subprocess.CalledProcessError as e:
                result.push = False
                result.error = f"git-push ({e.returncode})"
                return result
        else:
            log.warning("(%s) Not pushing local changes (ahead %d)", repo.name, status.ahead)

    if status.behind > 0:
        branch = status.head.branch
        if branch is None:
            result.merge = False
            result.error = "HEAD is detached"
            return result
        
        if branch.upstream is None:
            result.merge = False
            result.error = "No remote branch configured"
            return result

        if options.merge.enabled:
            try:
                repo.merge(
                    branch.upstream,
                    ff=options.merge.ff,
                    ff_only=options.merge.ff_only,
                    message=options.merge.message,
                    log_count=options.merge.log,
                    quiet=options.quiet,
                    verbose=options.verbose,
                )

                result.merge = True
            except subprocess.CalledProcessError as e:
                result.merge = False
                result.error = f"git-merge ({e.returncode})"
                return result
        else:
            log.warning("(%s) Not merging remote changes (behind %d)", repo.name, status.behind)

    return result


def _render_result(value: Optional[bool]) -> Union[str, Text]:
    if value is True:
        return Text("Success", style="green")
    if value is False:
        return Text("Error", style="red")
    return Text("-")


CMD_HELP = "Synchronize changes with remote by performing fetch and pull operations"
CMD_EPILOG = """
If local and remote histories have diverged, all further operations are aborted.
Many of the options are passed directly to internal git commands. Refer to documentations of git-fetch(1) and git-merge(1) for more details on the usage of these options.
"""

@app.command("sync", help=CMD_HELP, epilog=CMD_EPILOG)
def cmd_sync(
    fetch: Annotated[bool, typer.Option(
        help="Fetch from remote (--no-fetch performs merges without fetching)",
    )] = True,
    fetch_all: Annotated[bool, typer.Option(
        "-a", "--all", 
        help="(git-fetch) Fetch all remotes",
    )] = False,
    fetch_tags:Annotated[bool, typer.Option(
        "-t", "--tags",
        help="(git-fetch) Fetch remote tags",
    )] = False,
    fetch_prune: Annotated[bool, typer.Option(
        "-p", "--prune",
        help="(git-fetch) Remove refs that have been deleted from the remote",
    )] = False,
    fetch_refetch: Annotated[bool, typer.Option(
        "--refetch",
        help="(git-fetch) Fetch all objects as a fresh clone would",
    )] = False,
    fetch_prune_tags: Annotated[bool, typer.Option(
        "-P", "--prune-tags",
        help="(git-fetch) Remove tags that no longer exist in the remote",
    )] = False,
    push: Annotated[bool, typer.Option(
        help="Push local changes to remote if local branch is ahead of the remote branch.",
    )] = True,
    merge: Annotated[bool, typer.Option(
        help="Merge remote-tracking branch if the local branch is behind its remote counterpart",
    )] = True,
    merge_ff: Annotated[Optional[bool], typer.Option(
        "--ff/--no-ff",
        help="(git-merge) --ff: Fast-forward when possible, --no-ff: Always commit a merge commit",
    )] = None,
    merge_ff_only: Annotated[Optional[bool], typer.Option(
        "--ff-only",
        help="(git-merge) Merge only when fast-fowarding is possible",
    )] = None,
    merge_message: Annotated[str, typer.Option(
        "-m",
        help="(git-merge) Merge commit message (if one is created)",
    )] = "Merge remote-tracking branch '{upstream}' into '{branch}'",
    merge_log: Annotated[int, typer.Option(
        "--log",
        help="(git-merge) Append one-line descriptions of maximum N commits being merged to the commit message"
    )] = 10,
    quiet: Annotated[bool, typer.Option(
        help="Pass --quiet flags to git-fetch and git-merge",
    )] = False,
    verbose: Annotated[bool, typer.Option(
        help="Pass --verbose flags to git-fetch and git-merge",
    )] = False,
    bail: Annotated[bool, typer.Option(
        "--bail",
        help="Abort all unstarted sync operations when a fetch fails (a non-zero exit code from git-fetch)",
    )] = True,
):
    if quiet and verbose:
        pass

    config = get_config()

    repos = find_repos(
        config.find_path,
        config.find_max_depth,
        config.include_hidden,
        Matcher(
            query_name=config.query_name,
            query_remote_name=config.query_remote_name,
            query_remote_url=config.query_remote_url,
            query_clean=config.query_clean,
            case_sensitive=config.matcher_case_sensitive,
            exact=config.matcher_exact,
        ),
    )

    options = SyncOptions(
        fetch=FetchOptions(
            enabled=fetch,
            all=fetch_all,
            tags=fetch_tags,
            prune=fetch_prune,
            prune_tags=fetch_prune_tags,
            refetch=fetch_refetch,
        ),
        push=PushOptions(enabled=push),
        merge=MergeOptions(
            enabled=merge,
            ff=merge_ff,
            ff_only=merge_ff_only,
            message=merge_message,
            log=merge_log,
        ),
        quiet=quiet,
        verbose=verbose,
        bail=bail,
    )

    state = SyncState()

    max_workers = max_threads(3 if fetch else 8, len(repos))
    log.info("Syncing %d repositories with %d workers", len(repos), max_workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        fs = (executor.submit(_sync_worker, repo, options, state)
              for repo in repos)
        
        try:
            done_fs = wait(fs, timeout=120.0).done
        except KeyboardInterrupt:
            log.warning("Aborting repository sync")
            for f in fs:
                f.cancel()
            raise

        results = [f.result() for f in done_fs]

    if results:
        results.sort(key=lambda res: str(res.repo.path))

    table = Table(pad_edge=False, box=None, show_header=True, header_style="underline")
    table.add_column("Name")
    table.add_column("Fetch")
    table.add_column("Push")
    table.add_column("Merge")
    table.add_column("Result")

    for result in results:
        table.add_row(
            str(result.repo.path.relative_to(config.find_path)),
            _render_result(result.fetch),
            _render_result(result.push),
            _render_result(result.merge),
            Text(result.error, style="red") if result.error else "",
        )

    get_console().print(table)