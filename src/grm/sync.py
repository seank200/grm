import argparse
import logging
import pygit2

from pathlib import Path
from pygit2.enums import MergeFlag, MergeAnalysis, MergePreference
from typing import Optional

from .find import RepoFilter, find_repos
from .options import subparsers, filter_parser


log = logging.getLogger(__name__)

parser = subparsers.add_parser(
    "sync",
    parents=[filter_parser],
    description="Fetch, then push local changes or merge remote changes",
    help="Fetch, then push local changes or merge remote changes",
)

parser.add_argument(
    "path",
    nargs="?",
    default=Path.cwd(),
    type=Path,
    help="repository search path [default: current working directory]",
)

parser.add_argument(
    "--ff-only",
    action="store_true",
    help="Perform a merge only if a fast-forward merge is possible",
)

parser.add_argument(
    "-d", "--depth",
    default=1,
    type=int,
    help="maximum search depth (0 for no recursion limit) [default: 0]"
)


def merge_ff(
    repo: pygit2.Repository,
    head: pygit2.Branch,
    upstream: pygit2.Branch,
) -> bool:
    try:
        repo.set_head(upstream.name)  # Pass str to prevent detached HEAD
        repo.checkout("HEAD")
        head.set_target(
            upstream.target,
            f"Fast-forward {upstream.target} {head.target}"  # reflog
        )

        log.info("merge: %s: Merged '%s' into '%s' (fast-forward))",
                 repo.workdir, upstream.branch_name, head.branch_name)
    except pygit2.GitError as e:
        log.error("merge: %s: error: Failed to merge '%s' into '%s'. %s",
                  repo.workdir, upstream.branch_name, head.branch_name, e)
        return False

    return True


def merge_normal(
    repo: pygit2.Repository,
    head: pygit2.Branch,
    upstream: pygit2.Branch,
) -> bool:
    user = repo.default_signature
    if not user:
        log.error("merge: %s: error: Failed to merge '%s' into '%s'."
                  "Failed to create a merge commit -- user not configured",
                  repo.workdir, upstream.branch_name, head.branch_name)
        return False

    try:
        repo.merge(upstream.target, flags=MergeFlag.FAIL_ON_CONFLICT)
        tree = repo.index.write_tree()
        msg = f"Merge '{upstream.branch_name}' into '{head.branch_name}'"
        merge_commit = repo.create_commit(
            reference_name="HEAD",
            author=user,
            committer=user,
            message=msg,
            tree=tree,
            parents=[head.target, upstream.target],
        )
    except pygit2.GitError as e:
        log.error("merge: %s: error: Failed to merge '%s' into '%s'. %s",
                  repo.workdir, upstream.branch_name, head.branch_name, e)
        return False

    log.info("merge: %s: Merged '%s' into '%s' (created commit %s)",
             repo.workdir, upstream.branch_name, head.branch_name,
             str(merge_commit.id)[:8])

    return True


def merge(
    repo: pygit2.Repository,
    ff_only: bool,
) -> tuple[pygit2.Repository, bool]:
    if repo.head_is_detached:
        log.error("merge: %s: error: Not merging. HEAD is detached.",
                  repo.workdir)
        return repo, False

    if repo.head_is_unborn:
        log.error("merge: %s: error: Not merging. No commits yet on '%s'",
                  repo.workdir, repo.head.shorthand)
        return repo, False

    head: Optional[pygit2.Branch] = repo.branches.get(repo.head.shorthand)
    if head is None:
        log.error("merge: %s: error: Unable to merge. '%s'(HEAD) is "
                  "not a branch", repo.workdir, repo.head.shorthand)
        return repo, False

    upstream: Optional[pygit2.Branch] = head.upstream
    if upstream is None:
        log.warning("merge: %s: Not merging '%s'. No remotes are configured",
                    repo.workdir, head.branch_name)
        return repo, False

    analysis, preference = repo.merge_analysis(upstream.target, "HEAD")

    if bool(analysis & MergeAnalysis.UP_TO_DATE):
        log.debug("merge: %s: Already up-to-date")
        return repo, True

    if bool(analysis & MergeAnalysis.NONE):
        log.error("merge: %s: error: Unable to merge unrelated history '%s' "
                  "into '%s'", repo.workdir, upstream.branch_name,
                  head.branch_name)
        return repo, False

    if bool(analysis & MergeAnalysis.UNBORN):
        log.error("merge: %s: error: Unable to merge '%s' into '%s', "
                  "which has no commits yet", repo.workdir,
                  upstream.branch_name, head.branch_name)
        return repo, False

    if bool(analysis & MergeAnalysis.FASTFORWARD):  # Fast-forward
        return repo, merge_ff(repo, head, upstream)

    elif ff_only or bool(preference & MergePreference.FASTFORWARD_ONLY):
        log.warning("merge: %s: warning: Not merging '%s' into '%s'. "
                    "Cannot fast-forward.", repo.workdir, upstream.branch_name,
                    head.branch_name)
        return repo, False

    elif bool(analysis & MergeAnalysis.NORMAL):  # 3-way merge (merge commit)
        return repo, merge_normal(repo, head, upstream)

    else:
        log.error("merge: %s: error: Unexpected merge analysis result: %r",
                  repo.workdir, analysis)
        return repo, False

    return repo, True


def cmd_sync(args: argparse.Namespace):
    repos = find_repos(
        args.path,
        max_depth=args.depth,
        filter=RepoFilter.create(args),
    )

    # for repo in repos:
    #     merge(repo, args.ff_only)
