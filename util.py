import os
import sys


def env_var(name: str, allow_null: bool = False) -> str | None:
    """A useful utility for validating the presence of an environment variable before
    loading"""
    if not allow_null and name not in os.environ:
        sys.exit(f"{name} was not set in the environment")
    if allow_null and name not in os.environ:
        return None
    value = os.environ[name]
    if not allow_null and value is None:
        sys.exit(f"The value of {name} in the environment cannot be empty")
    return value
