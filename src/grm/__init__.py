__version__ = "0.1.0"

import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Optional
import typer

from grm.clone import app as clone_app
from grm.fetch import app as fetch_app
from grm.find import app as find_app
from grm.util import ConsoleHandler, GrmException, InvalidArgsError, UserAbort


APP_NAME = "grm"
APP_HELP = f"Git Repository Manager v{__version__}"

app = typer.Typer(name=APP_NAME, help=APP_HELP)

app.add_typer(fetch_app)
app.add_typer(find_app)
app.add_typer(clone_app)

log = logging.getLogger(__name__)


@app.command("version", help="Print program version")
def cmd_version():
    print(__version__)


def main():
    try:
        app()
    except InvalidArgsError as exc:
        log.error(
            "ERROR: %s. %s",
            exc,
            exc.__cause__ or "",
            exc_info=log.isEnabledFor(logging.DEBUG),
        )
        exit(2)
    except GrmException as exc:
        log.error(
            "ERROR: %s. %s",
            exc,
            exc.__cause__ or "",
            exc_info=log.isEnabledFor(logging.DEBUG),
        )
        exit(1)
    except UserAbort:
        log.warning(
            "Operation aborted by user",
            exc_info=log.isEnabledFor(logging.DEBUG),
        )
        exit(130)
    except Exception as exc:
        log.critical("ERROR: %s", exc, exc_info=True)
        exit(1)


@app.callback()
def callback(
    cwd: Annotated[Optional[Path], typer.Option(
        "-C", "--cwd",
        help=f"Run as if {APP_NAME} was invoked from this path",
    )] = None,
    color: Annotated[Optional[bool], typer.Option(
        envvar="GRM_COLOR",
        show_default="auto-detect",
        help="Always/never enable colors in logs",
    )] = None,
    debug: Annotated[bool, typer.Option(
        envvar="GRM_DEBUG",
        hidden=True,
    )] = False,
):
    handler = ConsoleHandler(sys.stderr, color=color)
    if debug:
        log.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            fmt="[%(name)s] %(message)s"
        ))
    else:
        log.setLevel(logging.INFO)
    log.addHandler(handler)

    if cwd:
        os.chdir(cwd)
