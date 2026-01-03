import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler


@dataclass
class Config:
    interactive: bool = True
    debug: bool = False
    verbose: bool = False


config = Config()
console = Console(stderr=True)
log = logging.getLogger(__name__)


def configure_logging():
    rich_handler = RichHandler(
        console=console,
        show_time=config.debug or config.verbose,
        omit_repeated_times=False,
        show_level=True,
        show_path=config.debug,
        rich_tracebacks=True
    )

    if config.debug:
        log_level = logging.NOTSET
        log_format = "[{name}]({threadName}) -- {message}"
    elif config.verbose:
        log_level = logging.INFO
        log_format = "{message}"
    else:
        log_level = logging.WARNING
        log_format = "{message}"

    rich_handler.setFormatter(logging.Formatter(fmt=log_format, style="{"))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(rich_handler)

    log.debug("Configured application. args: %s", sys.argv)