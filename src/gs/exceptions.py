import subprocess
from pathlib import Path
from typing import Optional


HOME = Path.home()


class CommandExit(Exception):
    def __init__(self, returncode: int = 1, *args: object):
        super().__init__(*args)
        self.returncode = returncode


class CommandError(CommandExit):
    def __init__(self, *args: object):
        super().__init__(1, *args)


class SubprocError(CommandError):
    @staticmethod
    def format_proc(path, returncode, cmd, stdout, stderr) -> str:
        s = ""
        if path is not None:
            if path.is_relative_to(HOME):
                s += f"'{path.relative_to(HOME)}' "
            else:
                s += f"'{path}' "
        s += f"({returncode}) "
        s += " ".join(cmd)
        if stdout:
            s += f"\n{stdout}".removesuffix("\n")
        if stderr:
            s += f"\n{stderr}"
        return s

    def __init__(
        self,
        cpe: subprocess.CalledProcessError,
        *args,
        path: Optional[Path]=None
    ):
        super().__init__(*args)
        self.cpe: subprocess.CalledProcessError = cpe
        self.path: Optional[Path] = path

    def __str__(self):
        return SubprocError.format_proc(
            self.path,
            self.cpe.returncode,
            self.cpe.cmd,
            self.cpe.stdout,
            self.cpe.stderr,
        )


class InvalidOptsError(CommandExit):
    def __init__(self, *args: object):
        super().__init__(2, *args)