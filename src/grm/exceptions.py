class GrmException(Exception):
    def __init__(self, *args, exit_code: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.exit_code: int = exit_code


class InvalidOptionsError(GrmException):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, exit_code=2, **kwargs)