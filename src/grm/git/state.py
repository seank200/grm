import enum
import os
import pygit2

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from pygit2.enums import FileStatus
from urllib.parse import urlparse


WT_ANY = (
    FileStatus.WT_DELETED
    | FileStatus.WT_MODIFIED
    | FileStatus.WT_NEW
    | FileStatus.WT_RENAMED
    | FileStatus.WT_TYPECHANGE
)
INDEX_ANY = (
    FileStatus.INDEX_DELETED
    | FileStatus.INDEX_MODIFIED
    | FileStatus.INDEX_NEW
    | FileStatus.INDEX_RENAMED
    | FileStatus.INDEX_TYPECHANGE
)


class GitOperation(enum.StrEnum):
    MERGE = "merge"
    REBASE = "rebase"
    REVERT = "revert"
    CHERRY_PICK = "cherry_pick"
    BISECT = "bisect"
    SEQUENCER = "sequencer"
    NONE = "-"


@dataclass
class RepoState:
    """
    Pickable object to processed repository state across processes.
    Primarily used for rendering, but can be used to perform state checks
    before writing to the index or working tree.
    """

    path: str

    is_bare: bool = False
    is_head_detached: bool = False
    is_head_unborn: bool = False

    operation: GitOperation = GitOperation.NONE
    shallow: bool = False  # whether this is a shallow repository

    untracked: int = 0  # untracked files in working tree
    worktree: int = 0  # (uncommitted) changes in working tree
    index: int = 0  # changes in index (added)

    ahead: int = -1  # local is ahead of remote
    behind: int = -1  # local is behind remote
    conflicted: int = 0  # conflicted files exist

    head: str = ""  # branch or oid
    upstream: str = ""  # remote-tracking branch of HEAD
    remote_url: str = ""
    remote_owner: str = ""
    remote_name: str = ""

    commit_time: int = 0  # HEAD commit time

    def indicators(self) -> str:
        s = ""
        if self.is_bare:
            s += "b"
        elif self.is_head_detached:
            s += "d"
        elif self.is_head_unborn:
            s += "u"
        else:
            s += "-"
        s += self.operation[0]
        s += "s" if self.shallow else "-"
        s += "u" if self.untracked else "-"
        s += "w" if self.worktree else "-"
        s += "i" if self.index else "-"
        s += "a" if self.ahead > 0 else "-"
        s += "b" if self.behind > 0 else "-"
        s += "c" if self.conflicted else "-"
        return s


def check_state(repos: list[pygit2.Repository]) -> list[RepoState]:
    """
    Check repository status

    :param repos: List of repositories
    :type repos: list[pygit2.Repository]
    :return: List of repository state
    :rtype: list[RepoState]
    """
    if len(repos) == 0:
        return []

    if len(repos) <= 4:
        return [_state_worker(r.workdir) for r in repos]

    n_workers = min(6, os.cpu_count() or 2)
    with ProcessPoolExecutor(max_workers=n_workers) as exec:
        states = exec.map(_state_worker, [r.workdir for r in repos])
        return [state for state in states]


def _state_worker(workdir: str) -> RepoState:
    repo = pygit2.Repository(workdir)

    state = RepoState(workdir)

    if repo.is_bare:
        state.is_bare = True
        return state

    if repo.head_is_unborn:
        state.is_head_unborn = True
        state.head = str(repo.references["HEAD"].target)
        return state

    if repo.head_is_detached:
        state.is_head_detached = True
        state.head = str(repo.head.target)[:8]
    else:
        branch_name = repo.head.shorthand
        head = repo.lookup_branch(repo.head.shorthand)
        state.head = branch_name
        if head.upstream:
            state.upstream = head.upstream.branch_name
            ahead, behind = repo.ahead_behind(head.target, head.upstream.target)
            state.ahead = ahead
            state.behind = behind

            try:
                state.remote_url = repo.remotes[head.upstream.remote_name].url or ""
            except KeyError:
                pass

    head_commit = repo.get(repo.head.target)
    if isinstance(head_commit, pygit2.Commit):
        state.commit_time = head_commit.commit_time

    if state.remote_url:
        parsed_url = urlparse(state.remote_url)
        if parsed_url.scheme and parsed_url.path:
            remote_path = PurePosixPath(parsed_url.path)
            state.remote_owner = str(remote_path.parent).removeprefix("/")
            state.remote_name = remote_path.name

    state.shallow = repo.is_shallow

    git_path = Path(repo.path)
    if (git_path / "rebase-merge").is_dir() or (git_path / "rebase-apply").is_dir():
        state.operation = GitOperation.REBASE
    elif (git_path / "MERGE_HEAD").is_file():
        state.operation = GitOperation.MERGE
    elif (git_path / "CHERRY_PICK_HEAD").is_file():
        state.operation = GitOperation.CHERRY_PICK
    elif (git_path / "REVERT_HEAD").is_file():
        state.operation = GitOperation.REVERT
    elif (git_path / "BISECT_LOG").is_file():
        state.operation = GitOperation.BISECT
    elif (git_path / "sequencer").is_dir():
        state.operation = GitOperation.SEQUENCER

    for file_status in repo.status(untracked_files="normal").values():
        if file_status & FileStatus.WT_NEW:
            state.untracked += 1
        elif file_status & WT_ANY:
            state.worktree += 1
        elif file_status & INDEX_ANY:
            state.index += 1
        elif file_status & FileStatus.CONFLICTED:
            state.conflicted += 1

    return state
