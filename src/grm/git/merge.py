from ..utils import run
from pathlib import Path


def merge_ff(path: Path, commit: str):
    run(("git", "merge", "--ff-only", commit), path)