import logging

from grm.exceptions import GrmException

from .config import parser, configure
from .find import parser as find_parser, cmd_find


log = logging.getLogger(__name__)

find_parser.set_defaults(cmd=cmd_find)
parser.set_defaults(cmd=None)


def main():
    args = parser.parse_args()
    configure(args)

    if args.cmd is None:
        parser.print_help()
        return 0

    try:
        return args.cmd(args) or 0
    except GrmException as e:
        log.critical("ERROR: %s", e)
        return e.returncode
    except KeyboardInterrupt:
        log.critical("Aborted")
    except Exception as e:
        log.critical("ERROR: %s", e, exc_info=True)

    return 1
