import argparse


OUTPUT_ABSOLUTE = "absolute"
OUTPUT_RELATIVE = "relative"
OUTPUT_URL = "url"
OUTPUT_LONG = "long"

EPILOG_LONG = """The long output format (option '-l' or '--output long')
prints the status of the working tree in the beginning of each line.
The status indicator is 7 characters wide in total ('iwuabcd'), with
each character indicating whether:
(i/-): change(s) exist in the index,
(w/-): change(s) exist in the working tree,
(u/-): untracked file(s) exist,
(a/-): local branch is ahead of the upstream branch (if configured),
(b/-): local branch is behind of the upstream branch (if configured),
(c/-): conflicted files exist (likely due to an ongoing merge),
(d/-): HEAD is detached."""


# Global parser object
parser = argparse.ArgumentParser(
    prog="grm",
    description="Git repository manager",
    epilog="Run grm [COMMAND] --help for further help on each subcommand"
)
parser.add_argument(
    "--no-env",
    action="store_true",
    help="ignore OS environment variables (GRM_*)",
)
log_group = parser.add_mutually_exclusive_group()
log_group.add_argument(
    "-v", "--verbose",
    action="store_true",
    help="Output more logs",
)
log_group.add_argument(
    "-q", "--quiet",
    action="store_true",
    help="Disable informational logs",
)
log_group.add_argument(
    "--debug",
    action="store_true",
    help=argparse.SUPPRESS,
)

# Subcommands
subparsers = parser.add_subparsers(title="subcommands")

# Parent parser for repository filter options
filter_parser = argparse.ArgumentParser(add_help=False)
filter_parser.add_argument(
    "-n", "--name",
    help="(filter) repository name",
)
filter_parser.add_argument(
    "-u", "--url",
    help="(filter) repository remote URL",
)
filter_parser.add_argument(
    "-C", "--case-sensitive",
    action="store_true",
    help="""(filter) perform case-sensitive matches on string filter
    queries [default: (case-insensitive)]""",
)
filter_parser.add_argument(
    "-e", "--exact",
    action="store_true",
    help="""(filter) perform exact string matches on string filter queries,
    [default: (substring match)]""",
)
filter_parser.add_argument(
    "--hidden",
    action="store_true",
    help="(filter) include hidden repositories (names starting with '.')"
)

render_parser = argparse.ArgumentParser(add_help=False)
render_parser.set_defaults(path=None)
output_group = render_parser.add_mutually_exclusive_group()
output_group.add_argument(
    "-o", "--output",
    choices=[
        OUTPUT_ABSOLUTE,
        OUTPUT_RELATIVE,
        OUTPUT_URL,
        OUTPUT_LONG,
    ],
    default=OUTPUT_RELATIVE,
    help=f"Output format ('{OUTPUT_ABSOLUTE}': absolute local path, "
    "'{OUTPUT_RELATIVE}': local path relative to the search directory, "
    "'{OUTPUT_URL}': all remote URLs, "
    "'{OUTPUT_LONG}': long format with current worktree status). "
    "[default: '{OUTPUT_RELATIVE}']",
)
output_group.add_argument(
    "-l",
    action="store_const",
    const=OUTPUT_LONG,
    help=f"Shorthand for setting '--output {OUTPUT_LONG}'",
    dest="output",
)
