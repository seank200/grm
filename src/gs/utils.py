import logging
import subprocess
import typer
from collections.abc import Sequence
from gs.exceptions import SubprocError
from pathlib import Path
from typing import Optional, TypeVar, Generic


HOME = Path.home()

log = logging.getLogger(__name__)


class OptionDef:
    ENV_PREFIX = "GS_"

    def __init__(
        self,
        *options: str,
        envvar: Optional[str] = None,
        help: Optional[str] = None,
    ):
        if not options:
            raise ValueError("options is required")

        self.options: Sequence[str] = options
        self._envvar: Optional[str] = envvar
        self.help: Optional[str] = help
    
    @property
    def name(self) -> str:
        option = self.options[0]
        i = option.find("/")
        if i > 0:
            option = option[:i]
        return option.lstrip("-").replace("-", "_").upper()
    
    @property
    def envvar(self) -> str:
        if self._envvar is None:
            return OptionDef.ENV_PREFIX + self.name

        return OptionDef.ENV_PREFIX + self._envvar

    def option(self, envvar: bool = False):
        kwargs = {}
        if envvar:
            kwargs["envvar"] = self.envvar
        if self.help:
            kwargs["help"] = self.help
        return typer.Option(*self.options, **kwargs)
    
    def argument(self, envvar: bool = False):
        kwargs = {}
        if envvar:
            kwargs["envvar"] = self.envvar
        if self.help:
            kwargs["help"] = self.help
        return typer.Argument(**kwargs)

    

T = TypeVar("T")


class Configurable(Generic[T]):
    def __init__(self):
        self.obj: Optional[T] = None

    def configure(self, obj: T):
        if self.obj is not None:
            raise RuntimeError("Already configured")
        self.obj = obj

    @property
    def value(self) -> T:
        if self.obj is None:
            raise RuntimeError("Used before configuration")
        
        return self.obj
    

def shrinkuser(path: Path) -> Path:
    if path.is_relative_to(HOME):
        return path.relative_to(HOME)
    return path


def run(
    args: Sequence[str],
    path: Path,
    *,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True
) -> subprocess.CompletedProcess:
    kwargs = {}
    if capture_output:
        kwargs["capture_output"] = True
        if text:
            kwargs["encoding"] = "utf-8"
            kwargs["text"] = True
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    try:
        proc = subprocess.run(args, cwd=path, check=check, **kwargs)
        if proc.returncode != 0:
            log.debug("Sub-command failed. %s", SubprocError.format_proc(
                path,
                proc.returncode,
                args,
                proc.stdout,
                proc.stderr,
            ))
        return proc
    except subprocess.CalledProcessError as cpe:
        e = SubprocError(cpe, path=path)
        log.warning("Sub-command failed. %s", e)
        raise e