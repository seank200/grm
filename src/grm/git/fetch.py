from grm.utils import run
from pathlib import Path


def fetch(path: Path, all: bool = False, prune: bool = False):
    args = ["git", "fetch"]
    if all:
        args.append("--all")
    if prune:
        args.append("--prune")

    run(args, path)