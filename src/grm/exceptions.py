class CommandError(Exception):
    def __init__(self, *args, returncode: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.returncode: int = returncode


class ArgValueError(CommandError):
    @staticmethod
    def format_message(message, arg: str = "", option: str = "", envvar: str = "") -> str:
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

    def __init__(self, message, *args, arg: str = "", option: str = "", envvar: str = "", **kwargs):
        super().__init__(
            ArgValueError.format_message(message, arg, option, envvar),
            *args,
            returncode=2,
            **kwargs
        )
