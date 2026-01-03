from dataclasses import dataclass
from pathlib import Path
from rich.text import Text
from .utils import run


@dataclass
class GitRemote:
    name: str
    url: str

    def __rich__(self):
        t = Text()
        t.append(self.name, style="bold")
        t.append(" " + self.url)
        return t


def get_remotes(path: Path) -> list[GitRemote]:
    proc = run("git remote".split(" "), path)

    remotes: list[GitRemote] = []

    for l in proc.stdout.splitlines():
        name = l.strip()
        if not name:
            continue

        url = run(f"git remote get-url {name}".split(" "), path).stdout
        remotes.append(GitRemote(name, url.strip()))

    return remotes