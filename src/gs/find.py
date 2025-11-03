import typer
from collections.abc import Collection
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from gs.options import SEARCH_ROOT, SEARCH_DEPTH, DEFAULT_DEPTH
from pathlib import Path
from typing import Annotated, Optional


app = typer.Typer()


def _find_git_dir(dir: Path, depth: int, executor: ThreadPoolExecutor) -> Collection[Path]:
    results: list[Path] = []
    if depth <= 0:
        return results

    for p in dir.iterdir():
        if p.is_dir():
            if (p / ".git").is_dir():
                results.append(p)
            elif depth > 1:
                executor.submit(_find_git_dir, p, depth-1, executor)
    
    return results
        


def find_git_dirs(search_root: Path, search_depth: int = 1) -> Collection[Path]:
    results: list[Path] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        executor.submit(_find_git_dir, search_root, search_depth, executor)

    return results


@app.command("find", help="Find git repositories")
def cmd_find(
    search_root: Annotated[Path, SEARCH_ROOT.option(envvar=True)],
    search_depth: Annotated[int, SEARCH_DEPTH.option(envvar=True)] = DEFAULT_DEPTH,
):
    pass