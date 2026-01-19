import os


def max_threads(*args: int):
    fallback: int = os.cpu_count() or 1

    if fallback > 8:
        fallback //= 2

    if args:
        return min(*args, fallback)

    return fallback
