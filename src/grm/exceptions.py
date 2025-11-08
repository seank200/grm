from pathlib import Path
from typing import Optional
from subprocess import CalledProcessError


HOME = Path.home()


class CommandExit(Exception):
    def __init__(self, returncode: int, *args):
        super().__init__(*args)
        self.returncode: int = returncode


class CommandAbort(CommandExit):
    def __init__(self, *args):
        super().__init__(1, *args)


class CommandError(CommandExit):
    def __init__(self, *args):
        super().__init__(1, *args)


class SubprocessError(CommandError):
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
        cpe: CalledProcessError,
        *args,
        path: Optional[Path] = None
    ):
        super().__init__(*args)
        self.cpe = cpe
        self.path = path

    def __str__(self):
        return super().__str__() \
            + "\n" \
            + SubprocessError.format_proc(
                self.path,
                self.cpe.returncode,
                self.cpe.cmd,
                self.cpe.stdout,
                self.cpe.stderr,
            )


class InvalidOptsError(CommandExit):
    def __init__(self, *args):
        super().__init__(2, *args)