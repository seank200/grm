import logging
import sys
from .config import parser as config_parser, cmd_config, configure, config
from .exceptions import CommandExit
from .fetch import parser as fetch_parser, cmd_fetch
from .find import parser as find_parser, cmd_find
from .ls import parser as ls_parser, cmd_ls
from .options import parser


log = logging.getLogger(__name__)

parser.set_defaults(func=None)
config_parser.set_defaults(func=cmd_config)
fetch_parser.set_defaults(func=cmd_fetch)
find_parser.set_defaults(func=cmd_find)
ls_parser.set_defaults(func=cmd_ls)


def main():
    args = parser.parse_args()

    try:
        configure(args)
    except CommandExit as e:
        print(f"command error: {e}", file=sys.stderr)
        return e.returncode

    try:
        if args.func:
            return args.func(args)
    except CommandExit as e:
        log.critical("%s", e, exc_info=config.debug)
        return e.returncode
    except Exception as e:
        log.critical("command error: %s", e, exc_info=True)
        return 1

    parser.print_help()
    return 2
