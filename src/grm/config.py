import logging
import sys
import typer
from dataclasses import dataclass, asdict
from pathlib import Path
from rich import print as rich_print
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    find_path: Path
    find_depth: int

    query_name: Optional[str]
    query_remote_url: Optional[str]
    query_clean: Optional[bool]

    matcher_case_sensitive: bool
    matcher_exact: bool

    debug: bool
    quiet: int
    color: Optional[bool]


@dataclass
class AppState:
    console: Console


config: Optional[AppConfig] = None
state: Optional[AppState] = None


def get_config() -> AppConfig:
    global config

    if config is None:
        raise RuntimeError("Application not configured")

    return config


def get_state() -> AppState:
    global state

    if state is None:
        raise RuntimeError("Application not initialized")
    
    return state


def configure(
    find_path: Annotated[Path, typer.Option(
        "-p", "--path",
        envvar="GRM_PATH",
        default_factory=Path.cwd,
        show_default="Current directory",
        help="Repository search root path",
    )],
    find_depth: Annotated[int, typer.Option(
        "-d", "--depth",
        envvar="GRM_DEPTH",
        help="Repository search depth",
    )] = 1,
    query_name: Annotated[Optional[str], typer.Option(
        "-n", "--name",
        help="(Search condition) Repository name",
    )] = None,
    query_remote_name: Annotated[Optional[str], typer.Option(
        "-r", "--remote",
        help="(Search condition) Repository remote name (e.g. 'origin')",
    )] = None,
    query_remote_url: Annotated[Optional[str], typer.Option(
        "-u", "--url",
        help="(Search condition) Repository remote url",
    )] = None,
    query_clean: Annotated[Optional[bool], typer.Option(
        "--clean/--dirty",
        help="(Search condition) Whether working tree contains/does not contain uncommitted changes to tracked files",
    )] = None,
    matcher_case_sensitive: Annotated[bool, typer.Option(
        "-c/-C", "--case-sensitive/--case-insensitive",
        envvar="GRM_MATCHER_CASE_SENSITIVE",
        help="Case sensitive search query",
    )] = False,
    matcher_exact: Annotated[bool, typer.Option(
        "-e", "--exact", 
        envvar="GRM_MATCHER_EXACT",
        help="Perform an exact match of search query (default: substring match)",
    )] = False,
    debug: Annotated[bool, typer.Option(
        "--debug",
        envvar="GRM_DEBUG",
        help="Output verbose logs for debugging (ignored when --quiet is set)",
    )] = False,
    quiet: Annotated[int, typer.Option(
        "-q", "--quiet",
        count=True,
        help="Suppress all logging (specify twice to suppress all output). Overrides --debug.",
    )] = 0,
    color: Annotated[Optional[bool], typer.Option(
        help="Always enable/disable color (default: enable when output is an interactive terminal)",
    )] = None,
):
    global config, state

    config = AppConfig(
        find_path=find_path.expanduser(),
        find_depth=find_depth,
        query_name=query_name,
        query_remote_url=query_remote_url,
        query_clean=query_clean,
        matcher_case_sensitive=matcher_case_sensitive,
        matcher_exact=matcher_exact,
        debug=debug,
        quiet=quiet,
        color=color,
    )

    state = AppState(
        console=Console(
            stderr=True,
            no_color=(None if color is None else (not color)),
        ),
    )

    pkg_log = logging.getLogger("grm")
    
    handler = RichHandler(
        show_time=debug,
        omit_repeated_times=False,
        show_level=debug,
        show_path=False,
        log_time_format="%Y-%m-%d %H:%M:%S",
    )

    if debug:
        handler.setFormatter(logging.Formatter(fmt="%(name)s: %(message)s"))
    
    pkg_log.addHandler(handler)
    pkg_log.setLevel(logging.DEBUG if debug else logging.INFO)

    log.debug("Application args: %s, cwd: %s", sys.argv, Path.cwd())


@app.command("config", help="Output current configuration")
def cmd_config():
    table = Table(pad_edge=False, box=None, show_header=False)
    table.add_column(style="cyan")
    table.add_column()

    for k, v in asdict(get_config()).items():
        table.add_row(k, str(v))

    rich_print(table)