import argparse


# Global parser object
parser = argparse.ArgumentParser(
    prog="grm",
    description="Git repository manager",
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
    help="(filter) perform case-senstivie matches on string filter queries",
)
filter_parser.add_argument(
    "-e", "--exact",
    action="store_true",
    help="""(filter) perform exact string matches on string filter queries,
    (default: substring match)""",
)
filter_parser.add_argument(
    "--hidden",
    action="store_true",
    help="(filter) include hidden repositories (names starting with '.')"
)
