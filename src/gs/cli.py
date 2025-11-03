import logging
import typer
from .context import configure_app
from .exceptions import (
    CommandExit,
    CommandError,
    SubprocError,
    InvalidOptsError
)
from .find import app as find_app
from .utils import OptionDef
from pathlib import Path
from typing import Annotated, Optional


DEBUG = OptionDef("--debug", help="Enable debug logging")
VERBOSE = OptionDef("--verbose", "-v", help="Enable verbose output")
NO_COLOR = OptionDef(
    "--no-color",
    help="Always disable color output. Color will be automatically disabled " \
        + "if output is not an interactive terminal"
)
CONFIG_HOME = OptionDef("--config-home", help="Path to configuraiton files directory")
DATA_HOME = OptionDef("--data-home", help="Path to data files directory")
LOG_FILE = OptionDef("--log-file/--no-log-file", help="Enable file logging")

app = typer.Typer(help="Manage git repositories")
app.add_typer(find_app)

log = logging.getLogger(__name__)


@app.callback()
def callback(
    debug: Annotated[bool, typer.Option(
        *DEBUG.options,
        envvar=DEBUG.envvar,
        help=DEBUG.help
    )] = False,
    verbose: Annotated[bool, typer.Option(
        *VERBOSE.options,
        envvar=VERBOSE.envvar,
        help=VERBOSE.help,
    )] = False,
    no_color: Annotated[Optional[bool], typer.Option(
        *NO_COLOR.options,
        envvar=NO_COLOR.envvar,
        help=NO_COLOR.help,
    )] = None,
    config_home: Annotated[Optional[Path], typer.Option(
        *CONFIG_HOME.options,
        envvar=CONFIG_HOME.envvar,
        help=CONFIG_HOME.help
    )] = None,
    data_home: Annotated[Optional[Path], typer.Option(
        *DATA_HOME.options,
        envvar=DATA_HOME.envvar,
        help=DATA_HOME.help
    )] = None,
    log_file_enabled: Annotated[bool, typer.Option(
        *LOG_FILE.options,
        envvar=LOG_FILE.envvar,
        help=LOG_FILE.help,
    )] = True,
):
    configure_app(
        debug=debug,
        verbose=verbose,
        no_color=no_color,
        config_home=config_home,
        data_home=data_home,
        log_file_enabled=log_file_enabled,
    )


def main():
    try:
        app()
        return 0
    except SubprocError as e:
        log.critical("Sub-command failed. %s", e)
    except CommandError as e:
        log.critical("Command error. %s", e)
    except InvalidOptsError as e:
        log.critical("Invalid option(s). %s", e)
    except CommandExit as e:
        if e.returncode == 0:
            log.info("%s", e)
        else:
            log.critical("Exiting. %s", e)
        return e.returncode
    except KeyboardInterrupt:
        print()
        log.critical("Aborted.")
    except Exception as e:
        log.critical("Unexpected internal error. %s", exc_info=True)

    return 1