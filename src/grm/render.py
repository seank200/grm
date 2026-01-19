import argparse
import pygit2
from collections.abc import Collection


def render_repos(
    repos: Collection[pygit2.Repository],
    args: argparse.Namespace,
):
    """Render repositories"""
    if not repos:
        return

    for repo in repos:
        print(repo.workdir)
