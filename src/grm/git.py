from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GitBranch:
    name: str
    is_head: bool = False
    upstream: str | None = None
    track: str | None = None


@dataclass
class GitRemote:
    name: str
    url: str


@dataclass
class GitWorktree:
    path: Path
    head: str
    branch: str | None = None
    prunable: str | None = None
    locked: str | None = None
    bare: bool = False


class GitRepository:
    def __init__(self, path: Path, *, resolve: bool = False):
        self.path = path

    @property
    def name(self) -> str:
        return self.path.name

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, value):
        return isinstance(value, GitRepository) and self.path == value.path
