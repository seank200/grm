class GrmException(Exception):
    def __init__(self, *args, returncode: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.returncode = returncode


class ArgValueError(GrmException):
    """User-supplied value (argument or config) is invalid"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, returncode=2, **kwargs)
