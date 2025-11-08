import logging
import typer
from .context import console_out
from .exceptions import SubprocessError
from .find import (
    find_repos,
    SEARCH_PATH,
    SEARCH_DEPTH,
    QUERY_NAME,
    QUERY_REMOTE
)
from .utils import OptionDef
from pathlib import Path
from rich.table import Table
from rich.text import Text
from typing import Annotated, Optional


app = typer.Typer()
log = logging.getLogger(__name__)


DETACH = OptionDef(
    "--detach",
    "-d",
    help="Allow detached head state when switching",
)


@app.command("switch", help="Switch repositories to a target ref")
def cmd_switch(
    refname: Annotated[str, typer.Argument(
        help="Target ref to switch to"
    )],
    path: Annotated[Path, typer.Option(
        *SEARCH_PATH.options,
        envvar=SEARCH_PATH.envvar,
        help=SEARCH_PATH.help,
        show_default="Current working directory",
        default_factory=Path.cwd,
    )],
    detach: Annotated[bool, typer.Option(
        *DETACH.options,
        help=DETACH.help,
    )] = False,
    depth: Annotated[int, typer.Option(
        *SEARCH_DEPTH.options,
        envvar=SEARCH_DEPTH.envvar,
        help=SEARCH_DEPTH.help,
    )] = 1,
    query_name: Annotated[Optional[str], typer.Option(
        *QUERY_NAME.options,
        help=QUERY_NAME.help,
    )] = None,
    query_remote: Annotated[Optional[str], typer.Option(
        *QUERY_REMOTE.options,
        help=QUERY_REMOTE.help,
    )] = None,
):
    _path = path.expanduser().resolve()
    repos = find_repos(
        _path,
        depth,
        query_name=query_name,
        query_remote=query_remote,
    )
    
    for repo in repos:
        try:
            repo.switch(refname, detach=detach)
        except SubprocessError:
            log.error(
                "Failed to switch [cyan]%s[/] to %s.",
                repo.name,
                refname,
                extra={"markup": True},
            )