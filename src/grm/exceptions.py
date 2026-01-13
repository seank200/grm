from typing import Optional


class GrmError(Exception):
    def __init__(self, *args, exit_code: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.exit_code = exit_code


class InvalidOptionsError(GrmError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, exit_code=2, **kwargs)