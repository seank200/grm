import logging
from pathlib import Path
import typer
from typing import Annotated, Optional

from grm.clone import app as clone_app
from grm.config import configure
from grm.util import GrmExit, GrmException, InvalidArgsError


NAME = "grm"
VERSION = "0.1.0"
DESCRIPTION = f"Git Repository Manager v{VERSION}"

app = typer.Typer(name=NAME, help=DESCRIPTION)
app.add_typer(clone_app)
log = logging.getLogger(__name__)


@app.callback()
def callback(
    cwd: Annotated[Optional[Path], typer.Option(
        "-C", "--cwd",
        help=f"Run as if {NAME} was launched at this path",
    )] = None,
    debug: Annotated[bool, typer.Option(
        "--debug",
        envvar="GRM_DEBUG",
        hidden=True,
        help="Enable debug level logging (overrides '--quiet')",
    )] = False,
    quiet: Annotated[bool, typer.Option(
        "--quiet",
        help="Suppress informational logs",
    )] = False,
    color: Annotated[Optional[bool], typer.Option(
        show_default="auto-detect",
        help="Always/never enable colored logging output",
    )] = None,
):
    configure(
        cwd=cwd,
        debug=debug,
        quiet=quiet,
        color=color,
    )


@app.command("version")
def cmd_version():
    print(VERSION)


def run():
    try:
        app()
    except InvalidArgsError as exc:
        log.error("ERROR: %s. %s", exc, exc.__cause__ or "")
        exit(2)
    except GrmException as exc:
        log.error("ERROR: %s", exc)
        exit(1)
    except GrmExit:
        log.warning("Operation aborted by user")
        exit(1)
    except Exception as exc:
        log.critical(
            "ERROR: %s",
            exc,
            exc_info=log.isEnabledFor(logging.INFO)
        )
        exit(1)
