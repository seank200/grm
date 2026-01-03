import typer
import logging
import sys
from pathlib import Path
from typing import Annotated
from .config import config, configure_logging
from .exceptions import GrmException, InvalidOptionsError
from .find import app as find_app

__version__ = "0.3.0"

app = typer.Typer()
app.add_typer(find_app)

log = logging.getLogger(__name__)


@app.callback()
def callback(
    interactive: Annotated[bool, typer.Option(
        envvar="GRM_INTERACTIVE",
        help="Ask for confirmation before performing bulk actions",
    )] = True,
    debug: Annotated[bool, typer.Option(
        "--debug",
        envvar="GRM_DEBUG",
        help="Enable debug mode",
    )] = False,
    verbose: Annotated[bool, typer.Option(
        "-v", "--verbose",
        envvar="GRM_VERBOSE",
        help="Enable verbose logging"
    )] = False,
):
    config.interactive = interactive
    config.debug = debug
    config.verbose = verbose

    configure_logging()


@app.command("version", help="Show program version and exit")
def cmd_version():
    print(__version__)


def main() -> int:
    try:
        app()
        return 0
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return 1
    except InvalidOptionsError as e:
        log.critical("Invalid option value. %s", e, exc_info=config.debug)
        return 2
    except GrmException as e:
        log.critical("Command failed. %s", e, exc_info=config.debug)
        return e.exit_code
    except Exception as e:
        log.critical("%s", e, exc_info=config.debug)
        return 1


if __name__ == "__main__":
    main()