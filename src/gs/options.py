from enum import Enum
from .utils import OptionDef


class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


SEARCH_ROOT = OptionDef(
    "--path", "-p",
    help="Root path to search for repositories"
)

SEARCH_DEPTH = OptionDef(
    "--depth", "-d",
    help="Maximum search depth from root path when searching for repositories"
)

DEFAULT_DEPTH = 1

FILTER_NAME = OptionDef(
    "--name", "-n",
    help="Filter by repository name (fuzzy match)"
)

FILTER_REMOTE = OptionDef(
    "--remote", "-r",
    help="Filter by repository remote (fuzzy match)"
)
