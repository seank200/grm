import logging
import sys
import typer
from dataclasses import dataclass, asdict
from pathlib import PurePath, Path
from rich import print as rich_print
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    find_path: Path
    find_max_depth: int

    query_name: Optional[str]
    query_remote_name: Optional[str]
    query_remote_url: Optional[str]
    query_clean: Optional[bool]
    matcher_case_sensitive: bool
    matcher_exact: bool

    debug: bool
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
        envvar="GRM_FIND_PATH",
        exists=True,
        file_okay=False,
        dir_okay=True,
        default_factory=Path.cwd,
        show_default="Current directory",
        help="Repository search root path",
    )],
    find_max_depth: Annotated[int, typer.Option(
        "-d", "--depth",
        envvar="GRM_FIND_MAX_DEPTH",
        help="Repository search depth",
    )] = 1,
    query_name: Annotated[Optional[str], typer.Option(
        "-n", "--name",
        help="(Search condition) Repository path basename",
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
        "-C", "--case-sensitive",
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
        help="Output verbose logs for debugging",
    )] = False,
    color: Annotated[Optional[bool], typer.Option(
        envvar="GRM_COLOR",
        help="Always enable/disable color (default: enabled when output is an interactive terminal)",
    )] = None,
):
    global config, state

    config = AppConfig(
        find_path=find_path.expanduser(),
        find_max_depth=find_max_depth,
        query_name=query_name,
        query_remote_name=query_remote_name,
        query_remote_url=query_remote_url,
        query_clean=query_clean,
        matcher_case_sensitive=matcher_case_sensitive,
        matcher_exact=matcher_exact,
        debug=debug,
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
        console=state.console,
    )

    if debug:
        handler.setFormatter(logging.Formatter(fmt="%(name)s: %(message)s"))
    
    pkg_log.addHandler(handler)
    pkg_log.setLevel(logging.DEBUG if debug else logging.INFO)

    log.debug("Application args: %s, cwd: %s", sys.argv, Path.cwd())


@app.command("config", help="Output current configuration")
def cmd_config():
    table = Table(pad_edge=False, box=None, show_header=False)
    table.add_column(style="bold")
    table.add_column()

    for k, v in asdict(get_config()).items():
        if v is None:
            _v = Text("None", style="dim")
        elif type(v) == bool:
            _v = Text(str(v), style="red")
        elif type(v) == str:
            _v = Text(f"'{v}'", style="green")
        elif type(v) == int or type(v) == float:
            _v = Text(str(v), style="cyan")
        elif isinstance(v, PurePath):
            _v = Text(str(v), style="magenta")
        else:
            _v = Text(str(v))

        table.add_row(k, _v)

    rich_print(table)


@app.command("path", help="Output repository search path")
def cmd_path():
    config = get_config()
    print(config.find_path)