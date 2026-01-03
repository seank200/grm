import logging
import subprocess
from collections.abc import Sequence, Iterable
from os import PathLike
from typing import Union


log = logging.getLogger(__name__)


def run(
    args: Union[str, bytes, PathLike[str], PathLike[bytes], Sequence[Union[str, bytes, PathLike[str], PathLike[bytes]]]],
    cwd: Union[str, bytes, PathLike[str], PathLike[bytes]],
    check: bool = True,
):
    try:
        proc = subprocess.run(args, cwd=cwd, check=check, capture_output=True,
                              text=True, encoding="utf-8")

        if log.isEnabledFor(logging.DEBUG):
            if proc.returncode == 0:
                log.debug("Process complete. args: %s.", args)
            else:
                stdout = proc.stdout.rstrip("\n") if proc.stdout else ""
                stderr = proc.stderr.rstrip("\n") if proc.stderr else ""

                log.debug(
                    "Process failed (%d). args: %s. %s %s",
                    proc.returncode,
                    args,
                    ("\n" + stdout) if stdout else "",
                    ("\n" + stderr) if stderr else "",
                )

        return proc
    except subprocess.CalledProcessError as e:
        log.warning(
            "Process failed (%d). args: %s. %s %s",
            e.returncode,
            args,
            ("\n" + e.stdout) if (e.stdout and e.stdout.rstrip("\n")) else "",
            ("\n" + e.stderr) if (e.stderr and e.stderr.rstrip("\n")) else "",
        )
        raise