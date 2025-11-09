from ..utils import run
from pathlib import Path


def push(path: Path):
    run(("git", "push"), path)