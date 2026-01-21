import logging

from .config import parser, configure, config_parser, cmd_config
from .exceptions import CommandError
from .find import find_parser, cmd_find


log = logging.getLogger(__name__)

config_parser.set_defaults(cmd=cmd_config)
find_parser.set_defaults(cmd=cmd_find)


def main():
    args = parser.parse_args()
    configure(args)

    try:
        returncode = args.cmd(args)
        return returncode if returncode else 0
    except KeyboardInterrupt:
        log.critical("Command aborted")
    except CommandError as e:
        log.critical("ERROR: %s", e)
        return e.returncode
    except Exception as e:
        log.critical("ERROR: %s", e, exc_info=True)

    return 1