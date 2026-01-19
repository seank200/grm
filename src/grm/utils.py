import os


def max_threads(*args: int):
    return min(*args, os.cpu_count() or 1)
