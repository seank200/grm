import logging
import sys
from .config import parser as config_parser, cmd_config, configure, config
from .exceptions import CommandExit
from .find import parser as find_parser, cmd_find
from .options import parser


log = logging.getLogger(__name__)

parser.set_defaults(func=None)
config_parser.set_defaults(func=cmd_config)
find_parser.set_defaults(func=cmd_find)


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

    print("program error: command entrypoint not configured", file=sys.stderr)
    parser.print_help()
    return 2
