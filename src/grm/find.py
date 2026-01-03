import logging
import os
import queue
import sys
import threading
import typer
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from rich import box
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional
from .config import config, console
from .exceptions import InvalidOptionsError
from .git import GitRepo


app = typer.Typer()
log = logging.getLogger(__name__)


class FindOutput(Enum):
    TABLE = "table"
    ABSOLUTE = "absolute"
    RELATIVE = "relative"


@dataclass
class FindOptions:
    path: Path
    depth: int
    filter_name: Optional[str]


@dataclass
class FindTask:
    path: Path
    depth: int


@dataclass
class FindContext:
    options: FindOptions
    tasks: queue.Queue[FindTask]
    results: list[Path]
    lock: threading.Lock
    aborted: bool = False


def _find_task(task: FindTask, ctx: FindContext):
    if ctx.aborted:
        return

    if (task.path / ".git").is_dir():
        name_matches = (not ctx.options.filter_name) or \
              (ctx.options.filter_name.lower() in task.path.name.lower())
        
        if name_matches:
            with ctx.lock:
                ctx.results.append(task.path)

        return
    
    if ctx.options.depth > 0 and task.depth >= ctx.options.depth:
        return
    
    with os.scandir(task.path) as it:
        for entry in it:
            if ctx.aborted:
                break
            if entry.is_dir(follow_symlinks=False):
                ctx.tasks.put(FindTask(Path(entry.path), task.depth+1))


def _find_worker(ctx: FindContext):
    task_count = 0
    tid = threading.get_native_id()

    try:
        task = ctx.tasks.get(timeout=0.05)
    except queue.Empty:
        log.debug("Thread %d terminated (no tasks available)")
        return

    while True:
        if ctx.aborted:
            break

        try:
            _find_task(task, ctx)
        except PermissionError:
            log.warning("No permission to search path: %s", task.path)
        except FileNotFoundError:
            log.warning("File not found: %s", task.path)
        except OSError as e:
            log.error("Failed to search %s. %s", task.path, e,
                      exc_info=config.debug)
        finally:
            task_count += 1
            ctx.tasks.task_done()

        try:
            task = ctx.tasks.get_nowait()
        except queue.Empty:
            break

    log.debug("Thread %d terminating (%d tasks)", tid, task_count)


def find(options: FindOptions) -> list[GitRepo]:
    if not options.path.is_dir():
        raise InvalidOptionsError(f"Path '{options.path}' is not a directory")

    num_workers = min(4, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        ctx = FindContext(
            options=options,
            tasks=queue.Queue(),
            results=[],
            lock=threading.Lock(),
        )

        ctx.tasks.put(FindTask(options.path, 0))
        fs = (executor.submit(_find_worker, ctx) for _ in range(num_workers))

        try:
            done_fs = wait(fs, timeout=60.0).done
        except KeyboardInterrupt:
            log.warning("Aborting repository search")
            ctx.aborted = True
            for f in fs:
                f.cancel()
            executor.shutdown()
            raise

        for f in done_fs:
            f.result()  # Raise any exceptions 

    return [GitRepo(p) for p in ctx.results]


def _search_path_callback(value: Path) -> Path:
    if value is None:
        raise typer.BadParameter("Must not be empty")
    
    if not value.is_dir():
        raise typer.BadParameter(f"'{value}' is not a directory")
    
    return value.expanduser()


@app.command("find", help="Search for local git repositories")
def cmd_find(
    search_path: Annotated[Path, typer.Argument(
        show_default="Current working directory",
        default_factory=Path.cwd,
        callback=_search_path_callback,
        help="Search root path",
    )],
    search_depth: Annotated[int, typer.Option(
        "-d", "--depth",
        help="Max search depth",
    )] = 2,
    filter_name: Annotated[Optional[str], typer.Option(
        "--name",
        help="Filter by repository name (contains, case-insensitive)",
    )] = None,
    sort: Annotated[bool, typer.Option(
        help="Sort search results by path name",
    )] = True,
    absolute: Annotated[Optional[bool], typer.Option(
        "-a", "--absolute",
        help="Output absolute paths",
    )] = None,
    verbose: Annotated[bool, typer.Option(
        "-v", "--verbose",
        help="Output detailed repository information",
    )] = False,
):
    resolved_path = search_path.resolve()

    log.info("Searching for repositories in %s ...", resolved_path)
    repos = find(FindOptions(
        path=resolved_path,
        depth=search_depth,
        filter_name=filter_name,
    ))

    if repos:
        log.info("Found %d repositories in %s", len(repos), resolved_path)
    else:
        log.warning("No repositories found in %s", resolved_path)

    if sort:
        log.debug("Sorting %d results...", len(repos))
        repos.sort(key=lambda r: str(r.path))

    if absolute is None:
        absolute = not sys.stdout.isatty()
    
    if not verbose:
        for r in repos:
            print(r.path if absolute else r.path.relative_to(resolved_path))
        return

    table = Table(pad_edge=False, box=None, header_style="bold underline dim")
    table.add_column("#", justify="right")
    table.add_column("Path")
    table.add_column("Remote")

    GitRepo.run(repos, remotes=True)

    for i, r in enumerate(repos):
        table.add_row(
            str(i+1),
            str(r.path if absolute else r.path.relative_to(resolved_path)),
            Text("\n").join((remote.__rich__() for remote in r.remotes())),
        )

    console.print(table)