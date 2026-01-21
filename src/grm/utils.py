import os


def max_threads(*args: int) -> int:
    cpu_count = os.cpu_count() or 1

    if cpu_count > 8:
        cpu_count //= 2

    if args:
        return min(*args, cpu_count)
    
    return cpu_count


def pl(count: int, singular: str, plural: str):
    """Return the plural form based on count"""

    return str(count) + " " + (singular if count == 1 else plural)