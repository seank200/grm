import logging
import os
import sys
from dataclasses import dataclass
from gs.exceptions import InvalidOptsError
from gs.options import CONFIG_HOME, DATA_HOME
from gs.utils import Configurable
from logging import NullHandler, Formatter
from logging.handlers import RotatingFileHandler
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from typing import Optional


DEFAULT_HOME = "gs"
ERR_SET_ENV = "Set environment variable '{}' to override."
ERR_DEFAULT_DIR = "Default {} '{}' already exists." + ERR_SET_ENV
ERR_NOT_DIR = "{} path '{}' is not a directory" + ERR_SET_ENV
FALLBACK_ENV_CONFIG_HOME = "XDG_CONFIG_HOME"
FALLBACK_ENV_DATA_HOME = "XDG_DATA_HOME"
LOG_FILE_NAME = "gs.log"
LOG_FILE_MAX_SIZE_BYTES = 8 * 1024
LOG_FILE_FORMAT = "{asctime} {levelname} ({threadname}) [{name}] -- {message}"


@dataclass
class AppContext:
    debug: bool
    verbose: bool
    config_home: Path
    data_home: Path
    console_err: Console


PACKAGE_NAME = __name__.split(".", 1)[0]

appcontext: Configurable[AppContext] = Configurable()
log = logging.getLogger(__name__)


def configure_app(
    debug: bool,
    verbose: bool,
    no_color: Optional[bool],
    config_home: Optional[Path],
    data_home: Optional[Path],
    log_file_enabled: bool,
):
    global appcontext

    console_err = Console(stderr=True, no_color=no_color)

    # Console logging
    rich_kwargs = {}
    if debug:
        package_level = logging.DEBUG
        console_level = logging.NOTSET
        rich_kwargs["rich_tracebacks"] = True
        rich_kwargs["omit_repeated_times"] = False
        rich_kwargs["log_time_format"] = "%Y-%m-%d %H:%M:%S"
    elif verbose:
        package_level = logging.DEBUG
        console_level = logging.INFO
        rich_kwargs["show_time"] = False
        rich_kwargs["show_path"] = False
        rich_kwargs["log_time_format"] = "%X"
    else:
        package_level = logging.INFO
        console_level = logging.WARNING
        rich_kwargs["show_time"] = False
        rich_kwargs["show_path"] = False
        rich_kwargs["log_time_format"] = "%X"

    package_logger = logging.getLogger(PACKAGE_NAME)
    package_logger.setLevel(package_level)

    console_handler = RichHandler(console=console_err, **rich_kwargs)
    package_logger.addHandler(console_handler)

    if debug or verbose:
        requests_logger = logging.getLogger("requests")
        requests_logger.setLevel(logging.WARNING)
        requests_logger.addHandler(console_handler)

    # Data home
    if data_home is None:
        env_data_home = os.environ.get(FALLBACK_ENV_DATA_HOME)
        if env_data_home:
            _data_home = (Path(env_data_home) / DEFAULT_HOME).expanduser()
        else:
            _data_home = Path.home() / ("." + DEFAULT_HOME) / "data"

        if _data_home.exists() and not _data_home.is_dir():
            raise InvalidOptsError(ERR_DEFAULT_DIR.format(
                "data home",
                _data_home,
                DATA_HOME.envvar,
            ))

        log.debug("Using default data home '%s'", _data_home)
    else:
        _data_home = data_home.expanduser()
        log.debug("Using data home '%s'", _data_home)

        if _data_home.exists() and not _data_home.is_dir():
            raise InvalidOptsError(ERR_NOT_DIR.format(
                "Data home",
                _data_home,
                DATA_HOME.envvar,
            ))

    # File logging
    if log_file_enabled:
        log_file_path = _data_home / LOG_FILE_NAME
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=LOG_FILE_MAX_SIZE_BYTES,
            backupCount=1
        )
        file_handler.setFormatter(Formatter(LOG_FILE_FORMAT))
        package_logger.addHandler(file_handler)

        log.debug("Debug logs will be saved at '%s'", log_file_path)

        if console_level is not None:
            console_handler.setLevel(console_level)
    else:
        log.debug("File logging is disabled. " \
                  + "Debug logs will be written to stderr.")

    # Config home
    if config_home is None:
        env_config_home = os.environ.get(FALLBACK_ENV_CONFIG_HOME)
        if env_config_home:
            _config_home = (Path(env_config_home) / DEFAULT_HOME).expanduser()
        else:
            _config_home = Path.home() / ("." + DEFAULT_HOME) / "config"

        if _config_home.exists() and not _config_home.is_dir():
            raise InvalidOptsError(ERR_DEFAULT_DIR.format(
                "config home",
                _config_home,
                CONFIG_HOME.envvar
            ))

        log.debug("Using default config home '%s'", _config_home)
    else:
        _config_home = config_home.expanduser()
        log.debug("Using config home '%s'", _config_home)

        if _config_home.exists() and not _config_home.is_dir():
            raise InvalidOptsError(ERR_NOT_DIR.format(
                "Config home",
                _config_home,
                CONFIG_HOME.envvar,
            ))

    appcontext.configure(AppContext(
        debug=debug,
        verbose=verbose,
        config_home=_config_home,
        data_home=_data_home,
        console_err=console_err
    ))

    log.debug("Configured application. args=%s, cwd=%s", sys.argv[1:], Path.cwd())