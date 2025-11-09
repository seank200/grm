import logging
from grm.exceptions import InvalidOptsError
from grm.utils import run
from pathlib import Path


log = logging.getLogger(__name__)


def switch(path: Path, refname: str, *, detach: bool = False):
    if not refname:
        raise InvalidOptsError("Switch target ref not specified")
    
    args: list[str] = ["git", "switch"]
    if detach:
        args.append("--detach")
    args.append(refname)

    run(args, path=path)

    log.debug("Switched %s to %s (detach: %s)", path, refname, detach)