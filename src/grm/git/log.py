from grm.utils import run
from pathlib import Path


COMPACT = "(%ar) %h %s"  # relative author date, abbrv. hash, subject


def git_log(
    path: Path,
    format: str = COMPACT,
    max_count: int = -1
) -> list[str]:
    args = ["git", "log"]

    if format:
        args.append("--format="+format)

    if max_count > 0:
        args.append("--max-count="+str(max_count))

    proc = run(args, path)
    if not proc.stdout:
        return []

    return [line.rstrip() for line in proc.stdout.splitlines()]
