from dataclasses import dataclass, field
import enum
from pathlib import Path


GRM_DIR = Path(".grm")
ARCHIVE_DIR = GRM_DIR / "archive"


class RemoteProvider(enum.Enum):
    GITHUB = "github"


@dataclass
class CloneOptions:
    owner: str
    """Remote repository owner (account or organization/group name)"""

    provider: str = "github"
    """Remote repository provider name (possible values: 'github')"""

    hostname: str | None = None
    """Hostname of the remote provider (for self-hosted providers)"""

    filters: list[str] = field(default_factory=list)
    """Repository clone URL path filter"""

    path_template: str = "{name}"
    """
    Python template string for local clone directory path
    (supported fields: 'owner', 'name')
    """

    prune: bool = False
    """Permanently delete repositories that no longer exist in remote"""

    archive: bool = True
    """
    Move repositories that no longer exist in remote to an
    archive directory
    """

    batch: bool = False
    """Disable confirmation prompts before pruning repositories"""


@dataclass
class FindOptions:
    depth: int = 0
    """Maximum search recursion depth (0 for no limit)"""

    hidden: bool = False
    """Include hidden files (starting with '.') in search"""

    filters: list[str] = field(default_factory=list)
    """Repository path filter (relative from search root path)"""


@dataclass
class FetchOptions:
    all: bool = False
    prune: bool = False
    tags: bool | None = None
    prune_tags: bool = False


@dataclass
class MergeOptions:
    ff: bool | None = None
    ff_only: bool = False
