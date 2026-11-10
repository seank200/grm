from fnmatch import fnmatch
import logging
import os
from pathlib import Path, PurePosixPath
import subprocess
from urllib.parse import urlparse


ANSI_RED = "\033[31m"  # ]
ANSI_YELLOW = "\033[33m"  # ]
ANSI_RESET = "\033[0m"  # ]

log = logging.getLogger(__name__)


class GrmException(Exception):
    ...


class InvalidArgsError(GrmException):
    def __init__(
        self,
        message: str,
        field: str = "",
        file: str | os.PathLike | None = None,
    ):
        prefix = "Invalid argument"
        if field:
            prefix += f" '{field}'"
        if file:
            prefix += f" (file '{file}')"
        super().__init__(f"{prefix}: {message}")


class UserAbort(BaseException):
    ...


class RemoteRepository:
    def __init__(self, provider: str, url: str):
        self.provider = provider
        self.url = url

        self._p_url = urlparse(url)
        self._path = PurePosixPath(self._p_url.path.removeprefix("/"))

    @property
    def hostname(self) -> str:
        return self._p_url.netloc

    @property
    def path(self) -> str:
        return str(self._path)

    @property
    def owner(self) -> str:
        return str(self._path.parent)

    @property
    def name(self) -> str:
        return self._path.name.removesuffix(".git")


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


def matches_globs(value: str, globs: list[str]) -> bool:
    matches: bool | None = None
    for pattern in globs:
        if pattern.startswith("!"):
            if fnmatch(value, pattern[1:]):
                matches = False
            elif matches is None:
                matches = True
        else:
            if fnmatch(value, pattern):
                matches = True
            else:
                matches = False

    return matches or False


def confirm(message: str = "Continue?"):
    if input(f"{message} (y/N) ").lower() not in ('y', 'yes'):
        raise UserAbort()


def parse_remote_url(url: str):
    """Parse remote repository owner and name from its URL"""
    path = PurePosixPath(urlparse(url).path.removeprefix("/"))
    owner = str(path.parent)
    name = path.name.removesuffix(".git")
    return owner, name
