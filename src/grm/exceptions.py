class CommandExit(Exception):
    def __init__(self, *args, returncode: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.returncode = returncode


class CommandError(CommandExit):
    MSG_PREFIX = "command failed: "

    def __init__(self, message: str = "", *args, **kwargs):
        super().__init__(
            CommandError.MSG_PREFIX + message,
            *args,
            returncode=1,
            **kwargs
        )


class ConfigError(CommandExit):
    MSG_PREFIX = "invalid config: "

    def __init__(self, message: str = "", *args, **kwargs):
        super().__init__(
            ConfigError.MSG_PREFIX + message,
            *args,
            returncode=2,
            **kwargs,
        )


class OptionError(CommandExit):
    MSG_PREFIX = "invalid arguments: "

    def __init__(self, message: str = "", *args, **kwargs):
        super().__init__(
            OptionError.MSG_PREFIX + message,
            *args,
            returncode=2,
            **kwargs,
        )
