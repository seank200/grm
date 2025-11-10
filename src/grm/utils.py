import logging
import os
import subprocess
from .exceptions import SubprocessError
from collections.abc import Collection, Sequence, Sized
from pathlib import Path
from rich.text import Text
from typing import Optional


HOME = Path.home()
log = logging.getLogger(__name__)


class OptionDef:
    ENV_PREFIX = "GRM_"

    def __init__(
        self,
        *options: str,
        envvar: Optional[str] = None,
        help: Optional[str] = None,
    ):
        self.options: tuple[str, ...] = options
        
        if envvar == "":
            self.envvar = None
        elif envvar is None:
            self.envvar = OptionDef.ENV_PREFIX + self.name
        else:
            self.envvar = OptionDef.ENV_PREFIX + envvar

        self.help = help

    @property
    def name(self) -> str:
        return self.options[0].split("/")[0] \
            .lstrip("-").replace("-", "_").upper()


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
            log.debug("Sub-process failed. %s", SubprocessError.format_proc(
                path,
                proc.returncode,
                args,
                proc.stdout,
                proc.stderr,
            ))
        return proc
    except subprocess.CalledProcessError as cpe:
        e = SubprocessError(cpe, "Sub-process failed.", path=path)
        log.debug("Sub-process failed. %s", e)
        raise e
    

def pl(obj, singular: str, plural: Optional[str] = None):
    """Return plural form of given word"""
    if issubclass(type(obj), Collection):
        count = len(obj)
    elif type(obj) is int:
        count = obj
    else:
        count = 1

    if count == 1:
        return singular

    if plural:
        return plural
    
    if singular.endswith(("s", "sh", "ch", "x", "z")):
        return singular + "es"
    
    if singular.endswith("y"):
        return singular.removesuffix("y") + "ies"
    
    if singular.endswith(("f", "fe")):
        return singular.removesuffix("e").removesuffix("f") + "ves"
    
    return singular + "s"


def num_workers(limit: int = 4) -> int:
    cpu_count = os.cpu_count()
    if cpu_count is None:
        cpu_count = 1
    return min(limit, cpu_count)


def render_result(result: Optional[bool]) -> Text:
    if result is None:
        return Text("~")
    if result:
        return Text("SUCCESS", style="bold green")
    return Text("ERROR", style="bold red")