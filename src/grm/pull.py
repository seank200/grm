import argparse
import enum
import logging
import pygit2

from pygit2.enums import (
    FileStatus,
    MergeAnalysis,
    MergeFlag,
    MergePreference,
    ResetMode,
)
from typing import Optional

from .config import subparsers, relative_workdir
from .exceptions import GitStateError
from .find import search_parser, find_repos_args
from .fetch import fetch_repos_args
from .utils import pl


class MergeOptions(enum.IntFlag):
    DEFAULT = enum.auto()
    FF = enum.auto()
    NO_FF = enum.auto()
    FF_ONLY = enum.auto()


log = logging.getLogger(__name__)

merge_parser = argparse.ArgumentParser(add_help=False)
ff_group = merge_parser.add_mutually_exclusive_group()
ff_group.add_argument("--ff", action="store_true")
ff_group.add_argument("--no-ff", action="store_true")
ff_group.add_argument("--ff-only", action="store_true")
merge_parser.add_argument("-p", "--prune", action="store_true")

pull_parser = subparsers.add_parser("pull", parents=[search_parser, merge_parser])
pull_parser.add_argument("repository", nargs="?", default="")


def parse_merge_options(args: argparse.Namespace) -> MergeOptions:
    options = MergeOptions.DEFAULT

    if args.ff_only:
        options |= MergeOptions.FF_ONLY
    elif args.ff:
        options |= MergeOptions.FF
    elif args.no_ff:
        options |= MergeOptions.NO_FF

    return options


def merge_normal(
    repo: pygit2.Repository, head: pygit2.Branch, ref: pygit2.Reference
) -> pygit2.Oid:
    user = repo.default_signature
    if user is None:
        raise GitStateError("Cannot create a merge commit - user not configured")

    repo.merge(ref.target, flags=MergeFlag.FAIL_ON_CONFLICT)
    upstream_name = ref.branch_name if isinstance(ref, pygit2.Branch) else ref.name
    tree = repo.index.write_tree()
    commit = repo.create_commit(
        "HEAD",
        user,
        user,
        f"Merge '{upstream_name}' into '{head.branch_name}'",
        tree,
        [head.target, ref.target],
    )
    repo.state_cleanup()
    return commit


def merge_ff(repo: pygit2.Repository, head: pygit2.Branch, ref: pygit2.Reference):
    reflog_message = f"Fast-forward {ref.target} {head.target}"
    head.set_target(ref.target, reflog_message)
    repo.reset(ref.target, ResetMode.HARD)


def _merge_upstream_repo(repo: pygit2.Repository, options: MergeOptions):
    if repo.head_is_unborn:
        raise GitStateError("HEAD is unborn (no commits)")

    if repo.head_is_detached:
        raise GitStateError("HEAD is detached")

    head: Optional[pygit2.Branch] = repo.branches.get(repo.head.shorthand)
    if head is None:
        raise GitStateError(f"'{repo.head.shorthand}'(HEAD) is not a branch")

    upstream: Optional[pygit2.Branch] = head.upstream
    if upstream is None:
        raise GitStateError(f"'{head.branch_name}' has no remote-tracking branch")

    analysis, preference = repo.merge_analysis(upstream.target, "HEAD")

    if analysis & MergeAnalysis.UP_TO_DATE:
        log.info(
            "merge: %s: '%s' is already up-to-date",
            relative_workdir(repo),
            head.branch_name,
        )
        return

    if analysis & MergeAnalysis.NONE:
        raise GitStateError(
            "Unable to merge unrelated histories ('{}', '{}')".format(
                upstream.name, head.name
            )
        )

    if analysis & MergeAnalysis.UNBORN:
        raise GitStateError(
            "Source '{}' is unborn (has no commits yet)".format(head.name)
        )

    if analysis & MergeAnalysis.FASTFORWARD and not options & MergeOptions.NO_FF:
        # Fast-forward
        merge_ff(repo, head, upstream)
        log.info(
            "merge: %s: Fast-forwarded '%s' into '%s'",
            relative_workdir(repo),
            upstream.branch_name,
            head.branch_name,
        )
        return

    # Cannot fast-forward. Check user preferences before continuing
    if (options & MergeOptions.FF_ONLY) or (
        preference & MergePreference.FASTFORWARD_ONLY
    ):
        raise GitStateError(
            "Cannot fast-forward '%s' into '%s' (diverged histories)",
            upstream.branch_name,
            head.branch_name,
        )

    if analysis & MergeAnalysis.NORMAL:
        merge_commit: pygit2.Oid = merge_normal(repo, head, upstream)
        log.info(
            "merge: %s: Merged '%s' into '%s' (merge commit: %s)",
            relative_workdir(repo),
            upstream.branch_name,
            head.branch_name,
            str(merge_commit)[:8],
        )
        return

    raise GitStateError("Invalid repository state: {!r}".format(analysis))


def merge_upstream_repo(
    repo: pygit2.Repository, options: MergeOptions
) -> tuple[pygit2.Repository, bool]:
    try:
        _merge_upstream_repo(repo, options)
        return repo, True
    except GitStateError as e:
        log.error("merge: %s: ERROR: Merge failed. %s", relative_workdir(repo), e)
    except pygit2.GitError as e:
        log.error("merge: %s: GIT ERROR: Merge failed. %s", relative_workdir(repo), e)

    return repo, False


def merge_upstream_repos(repos: list[pygit2.Repository], options: MergeOptions):
    n_total = len(repos)
    log.info("Updating %d %s", n_total, pl(n_total, "repository", "repositories"))
    n_success = 0
    for repo in repos:
        _, success = merge_upstream_repo(repo, options)
        n_success += int(success)
    log.info("Merge complete: %d success, %d failed\n", n_success, n_total - n_success)


def cmd_pull(args: argparse.Namespace):
    repos = find_repos_args(args)
    fetched_repos = fetch_repos_args(repos, args)
    merge_upstream_repos(fetched_repos, parse_merge_options(args))
