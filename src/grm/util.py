from dataclasses import dataclass
from fnmatch import fnmatch
import logging
import os
from pathlib import Path, PurePosixPath, PurePath
import subprocess
from urllib.parse import urlparse


ANSI_RED = "\033[31m"  # ]
ANSI_YELLOW = "\033[33m"  # ]
ANSI_RESET = "\033[0m"  # ]

log = logging.getLogger(__name__)


class GrmException(Exception):
    ...


class InvalidArgsError(GrmException):
    ...


class GrmExit(BaseException):
    ...


class InvalidConfigError(InvalidArgsError):
    def __init__(
        self,
        message: str,
        field: str = "",
        file: os.PathLike | None = None,
    ):
        prefix = "Invalid config"
        if field:
            prefix += f" property '{field}'"
        if file:
            prefix += f" in file '{file}'"
        super().__init__(f"{prefix}: {message}")


class ConsoleHandler(logging.StreamHandler):
    def __init__(self, stream, color: bool | None = None):
        super().__init__(stream)
        self.color_preference = color
        self.color_enabled = self.should_enable_color()

    def format(self, record: logging.LogRecord):
        msg = super().format(record)

        if self.color_enabled:
            if record.levelno >= logging.ERROR:
                color = ANSI_RED
            elif record.levelno >= logging.WARNING:
                color = ANSI_YELLOW
            else:
                color = ""

            return f"{color}{msg}{ANSI_RESET}"

        return msg

    def setStream(self, stream):
        result = super().setStream(stream)
        self.color_enabled = self.should_enable_color()
        return result

    def should_enable_color(self) -> bool:
        if self.color_preference is not None:
            return self.color_preference

        if os.name != "posix":
            return False

        isatty = getattr(self.stream, "isatty")

        try:
            return isatty and isatty()
        except Exception:
            return False


@dataclass(frozen=True)
class RemoteRepository:
    provider: str
    url: str

    def parse_url(self):
        return parse_remote_url(self.url)

    def path(self) -> PurePath:
        return PurePosixPath(urlparse(self.url).path.removeprefix("/"))

    # @property
    # def owner(self) -> str:
    #     return str(self.path().parent)
    #
    # @property
    # def name(self) -> str:
    #     return self.path().name.removesuffix(".git")


def run_cmd(cwd: Path | None, args):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        log.debug(
            "subprocess error (%d). cwd=[%s], args=%s, stderr=%s",
            exc.returncode,
            cwd,
            args,
            exc.stderr,
        )
        raise


def matches_globs(value: str | PurePath, globs: list[str]) -> bool:
    _value = value if type(value) is str else str(value)
    matches: bool | None = None
    for pattern in globs:
        if pattern.startswith("!"):
            if fnmatch(_value, pattern[1:]):
                matches = False
            elif matches is None:
                matches = True
        else:
            if fnmatch(_value, pattern):
                matches = True

    return matches or False


def confirm(message: str = "Continue?") -> bool:
    return input(f"{message} (y/N) ").lower() in ('y', 'yes')


def parse_remote_url(url: str):
    """Parse remote repository owner and name from its URL"""
    path = PurePosixPath(urlparse(url).path.removeprefix("/"))
    owner = str(path.parent)
    name = path.name.removesuffix(".git")
    return owner, name
