import logging
import sys
from dataclasses import dataclass
from logging import Formatter, NullHandler
from pathlib import Path
from typing import Optional, Any
from rich.console import Console
from rich.logging import RichHandler


@dataclass
class GlobalOptions:
    debug: bool = False
    verbose: bool = False
    color: Optional[bool] = None


FORMAT_SHORT = "{message}"
FORMAT_LONG = "[{threadName}] ({name}) -- {message}"
TIME_FORMAT_SHORT = "%H:%M:%S"
TIME_FORMAT_LONG = "%Y-%m-%d %H:%M:%S"
PACKAGE_NAME = __name__.split(".", 1)[0]
console_out = Console()
console_err = Console(stderr=True)
root_logger = logging.getLogger()
log = logging.getLogger(__name__)
options = GlobalOptions()


def configure(
    debug: bool,
    verbose: bool,
    color: Optional[bool]
):
    """Configure application"""
    kwargs: dict[str, Any] = { "show_path": False }

    if debug:
        level = logging.DEBUG
        format = FORMAT_LONG
        kwargs["omit_repeated_times"] = False
        kwargs["log_time_format"] = TIME_FORMAT_LONG
    elif verbose:
        level = logging.INFO
        format = FORMAT_SHORT
        kwargs["log_time_format"] = TIME_FORMAT_SHORT
    else:
        level = logging.WARNING
        format = FORMAT_SHORT
        kwargs["show_time"] = False

    handler = RichHandler(console=console_err, **kwargs)
    handler.setFormatter(Formatter(format, style="{"))
    root_logger.setLevel(logging.WARNING)
    root_logger.addHandler(NullHandler())
    pkg_logger = logging.getLogger(PACKAGE_NAME)
    pkg_logger.setLevel(level)
    pkg_logger.addHandler(handler)

    if color is not None:
        console_out.no_color = not color
        console_err.no_color = not color

    log.debug(
        "Configured application. args=%s, cwd=%s",
        sys.argv[1:],
        Path.cwd()
    )