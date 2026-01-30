import argparse
import pygit2

from datetime import datetime, timedelta
from grm.exceptions import ArgValueError
from grm.git import check_state
from pathlib import Path, PurePath
from rich import print as rich_print
from rich.columns import Columns
from rich.table import Table


NOW = datetime.now()
YEAR_THRESHOLD = timedelta(days=180)
FMT_YEAR = "%d %b, %Y"
FMT_TIME = "%d %b %H:%M"


parent_parser = argparse.ArgumentParser(add_help=False)

output_group = parent_parser.add_mutually_exclusive_group()
output_group.add_argument(
    "-l", action="store_true", dest="output_long", help="Print one repository per line"
)
output_group.add_argument(
    "-1", action="store_true", dest="output_one", help="Print in long format (slow)"
)


def render_repos(
    repos: list[pygit2.Repository],
    *,
    relative_to: Path,
    one: bool = False,
    long: bool = False,
    sort: bool = True,
):
    if one and long:
        raise ArgValueError("Multiple output formats specified")

    if not long:
        relative_paths = [
            str(PurePath(repo.workdir).relative_to(relative_to)) for repo in repos
        ]

        if sort:
            relative_paths.sort()

        if one:
            for p in relative_paths:
                print(p)
        else:
            columns = Columns(relative_paths)
            rich_print(columns)

        return

    repo_states = check_state(repos)

    if sort:
        repo_states.sort(key=lambda s: s.path)

    table = Table(
        show_header=False,
        show_footer=False,
        pad_edge=False,
        box=None,
    )
    for state in repo_states:
        if state.commit_time:
            commit_time_dt = datetime.fromtimestamp(state.commit_time)
            if abs(commit_time_dt - NOW) > YEAR_THRESHOLD:
                fmt = FMT_YEAR
            else:
                fmt = FMT_TIME
            commit_time = commit_time_dt.strftime(fmt)
        else:
            commit_time = ""

        table.add_row(
            state.indicators(),
            state.head or "-",
            state.remote_owner or "-",
            commit_time or "{:<12}".format("-"),
            str(PurePath(state.path).relative_to(relative_to)),
        )

    rich_print(table)
