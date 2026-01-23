class CommandError(Exception):
    def __init__(self, *args, returncode: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.returncode: int = returncode


class GitStateError(CommandError):
    """
    Operation cannot continue due to invalid repository state
    (e.g. HEAD is detached, head is unborn, etc.)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ProcedureError(CommandError):
    """
    Internal procedure error.
    Raised to abort procedures for a single repository, but to let
    the program continue work on other repositories
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, returncode=1, **kwargs)


class ArgValueError(CommandError):
    @staticmethod
    def format_message(
        message, arg: str = "", option: str = "", envvar: str = ""
    ) -> str:
        prefix = "Invalid "
        if arg:
            prefix += f"argument '{arg}': "
        elif option:
            prefix += f"option '{option}': "
        elif envvar:
            prefix += f"environment variable '{envvar}': "
        else:
            prefix += "argument: "

        return prefix + message

    def __init__(
        self,
        message,
        *args,
        arg: str = "",
        option: str = "",
        envvar: str = "",
        **kwargs,
    ):
        super().__init__(
            ArgValueError.format_message(message, arg, option, envvar),
            *args,
            returncode=2,
            **kwargs,
        )
