import argparse
import concurrent.futures
import logging
import pygit2

from .config import subparsers
from .find import search_parser, find_repos_args
from .utils import pl


log = logging.getLogger(__name__)

fetch_parser = subparsers.add_parser("fetch", parents=[search_parser])
fetch_parser.add_argument("-r", "--remote", default="", help="Remote name", dest="remote_name")
fetch_parser.add_argument("-p", "--prune", action="store_true")


def fetch_repos(repos: list[pygit2.Repository], remote_name: str = ""):
    pass


def fetch_repos_args(repos: list[pygit2.Repository], args):
    log.info("Fetching %s", pl(len(repos), "repository", "repositories"))
    log.info("Fetch complete: %d success, %d failed")


def cmd_fetch(args):
    repos = find_repos_args(args)