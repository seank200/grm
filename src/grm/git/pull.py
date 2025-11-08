from grm.utils import run
from pathlib import Path


def pull_ff(path: Path):
    run(["git", "pull", "--ff"], path)