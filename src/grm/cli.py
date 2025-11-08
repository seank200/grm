import logging
import typer
from .context import options, configure
from .exceptions import CommandExit, CommandError, SubprocessError, CommandAbort, InvalidOptsError
from .fetch import app as fetch_app
from .find import app as find_app
from .status import app as status_app
from .switch import app as switch_app
from .utils import OptionDef
from typing import Annotated, Optional


app = typer.Typer(help="Git Repository Manager")
app.add_typer(find_app)
app.add_typer(status_app)
app.add_typer(fetch_app)
app.add_typer(switch_app)
log = logging.getLogger(__name__)


DEBUG = OptionDef(
    "--debug",
    help="Enable detailed logging for debugging"
)

VERBOSE = OptionDef(
    "--verbose",
    "-v",
    help="Enable verbose output"
)

COLOR = OptionDef(
    "--color/--no-color",
    help="Always enable/disable color. (Default: auto)"
)

@app.callback()
def callback(
    debug: Annotated[bool, typer.Option(
        *DEBUG.options,
        envvar=DEBUG.envvar,
        help=DEBUG.help
    )] = options.debug,
    verbose: Annotated[bool, typer.Option(
        *VERBOSE.options,
        envvar=VERBOSE.envvar,
        help=VERBOSE.help,
    )] = options.verbose,
    color: Annotated[Optional[bool], typer.Option(
        *COLOR.options,
        envvar=COLOR.envvar,
        help=COLOR.help,
    )] = options.color
):
    configure(debug, verbose, color)


def main():
    try:
        app()
        return 0
    except SubprocessError as e:
        log.critical("Sub-process(%s) error. %s", e.cpe.cmd[0], e)
    except CommandAbort as e:
        log.critical("Command aborted. %s", e)
    except CommandError as e:
        log.critical("Command error. %s", e)
    except InvalidOptsError as e:
        log.critical("Invalid options. %s", e)
        return 2
    except CommandExit as e:
        if e.returncode == 0:
            log.info("%s", e)
        else:
            log.critical("Command exit. %s", e)
        return e.returncode
    except KeyboardInterrupt:
        print()
        log.critical("Command aborted")
    except Exception as e:
        log.critical("Command error. %s", e, exc_info=True)

    return 1