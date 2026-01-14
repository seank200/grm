import logging
import typer
from .config import configure, get_config, app as config_app
from .exceptions import GrmError


app = typer.Typer(callback=configure)
app.add_typer(config_app)

log = logging.getLogger(__name__)


def main():
    try:
        app()
        return 0
    except KeyboardInterrupt:
        print()
    except GrmError as e:
        log.critical("Command failed: %s", e)
        return e.exit_code
    except Exception as e:
        log.critical("Command error: %s", e, exc_info=True)
    return 1


@app.command("path", help="Output repository search path")
def cmd_path():
    config = get_config()
    print(config.find_path)