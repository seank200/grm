from grm.utils import run
from pathlib import Path
from typing import Optional


def fetch(path: Path, remote: Optional[str] = "", *, all: bool = False, prune: bool = False):
    args = ["git", "fetch"]
    if prune:
        args.append("--prune")
    if all:
        args.append("--all")
    elif remote:
        args.append(remote)

    run(args, path)