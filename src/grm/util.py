from dataclasses import dataclass
import enum
from fnmatch import fnmatch
import logging
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Literal, Union
from urllib.parse import urlparse


ANSI_BLACK = "\033[30m"  # ]
ANSI_RED = "\033[31m"  # ]
ANSI_GREEN = "\033[32m"  # ]
ANSI_YELLOW = "\033[33m"  # ]
ANSI_BLUE = "\033[34m"  # ]
ANSI_MAGENTA = "\033[35m"  # ]
ANSI_CYAN = "\033[36m"  # ]
ANSI_WHITE = "\033[37m"  # ]
ANSI_DEFAULT = "\033[38m"  # ]

ANSI_RESET = "\033[0m"  # ]
ANSI_BOLD = "\033[1m"  # ]

ANSI_COLORS: dict[str, str] = {
    "black": ANSI_BLACK,
    "red": ANSI_RED,
    "green": ANSI_GREEN,
    "yellow": ANSI_YELLOW,
    "blue": ANSI_BLUE,
    "magenta": ANSI_MAGENTA,
    "cyan": ANSI_CYAN,
    "white": ANSI_WHITE,
    "default": ANSI_DEFAULT,
}

log = logging.getLogger(__name__)


AnsiColor = Literal['black'] | Literal['red'] | Literal['green'] \
        | Literal['yellow'] | Literal['blue'] | Literal['magenta'] \
        | Literal['cyan'] | Literal['white'] | Literal['default']


class GrmException(Exception):
    ...


class InvalidArgsError(GrmException):
    def __init__(
        self,
        message: str,
        field: str = "",
        file: str | os.PathLike | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.file = file

    def __str__(self):
        s = "Invalid "
        s += "config " if self.file else "argument "
        if self.field:
            s += f" '{self.field}'"
        if self.file:
            s += f" (file '{self.file}')"

        return f"{s}: {super().__str__()}"


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


@dataclass
class TextValue:
    value: str
    color: AnsiColor | None
    bold: bool
    reset: bool

    def has_style(self) -> bool:
        return bool(self.color) or self.bold or self.reset

    def __str__(self):
        if self.color:
            s = ANSI_COLORS[self.color]
        else:
            s = ""

        if self.bold:
            s += ANSI_BOLD

        s += self.value

        if self.reset:
            s += ANSI_RESET

        return s


class Text:
    def __init__(
        self,
        value: str | None,
        *,
        color: AnsiColor | None = None,
        bold: bool = False,
        reset: bool = False,
    ):
        if value is None:
            self._values: list[TextValue] = []
        else:
            self._values: list[TextValue] = [
                TextValue(value=value, color=color, bold=bold, reset=reset),
            ]
        self.style: bool = True

    def append(self, value: Union[str, "Text"]):
        if type(value) is str:
            self._values[-1].value += value
        elif isinstance(value, Text):
            self._values.extend(value._values)
        else:
            raise TypeError(f"Unsupported value type: {type(value).__name__}")

    def plain(self) -> str:
        return "".join(v.value for v in self._values)

    def format(self, *args, **kwargs):
        return self.__str__().format(*args, **kwargs)

    def __str__(self):
        if self.style:
            s = ""
            for v in self._values:
                if v.color:
                    s += ANSI_COLORS[v.color]
                if v.bold:
                    s += ANSI_BOLD
                s += v.value
                if v.reset:
                    s += ANSI_RESET
            return s

        return self.plain()

    def __bool__(self):
        return any(bool(v.value) for v in self._values)

    def __add__(self, other):
        t = Text(None)
        t.append(self)

        if type(other) is str or isinstance(other, Text):
            t.append(other)
            return t

        return NotImplemented

    def __mul__(self, other):
        if type(other) is int:
            t = Text(None)
            for _ in range(other):
                t.append(self)
            return t

        return NotImplemented


class ConsoleHandler(logging.StreamHandler):
    def __init__(self, stream, color: bool | None = None):
        super().__init__(stream)
        self.color_preference = color
        self.color_enabled = self.should_enable_color()

    def format(self, record: logging.LogRecord):
        if record.args:
            for arg in record.args:
                if isinstance(arg, Text):
                    arg.style = self.color_enabled

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


def run_cmd(cwd: Path | None, args, timeout: float | None = 10.0):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
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
    except subprocess.TimeoutExpired as exc:
        log.debug(
            "subprocess timeout (%f s). cwd=[%s], args=%s, output=%s\n%s",
            exc.timeout,
            cwd,
            args,
            exc.stderr,
            exc.stdout,
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
