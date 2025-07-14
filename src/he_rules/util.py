from collections.abc import Awaitable, Callable
from functools import wraps
import os
import sys
from typing import Concatenate, ParamSpec, TypeVar

from fastmcp.server.dependencies import get_context
from sqlmodel import Session


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


P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


def transactional(
    m: Callable[Concatenate[T, Session, P], Awaitable[R]],
) -> Callable[Concatenate[T, P], Awaitable[R]]:
    """Convenient wrapper for passing a session into your method and commiting any changes you
    make.
    """

    @wraps(m)
    async def inner(self: T, *args: P.args, **kwargs: P.kwargs) -> R:
        engine = get_context().fastmcp.db_engine  # type: ignore[attr-defined]
        with Session(engine) as session:
            result = await m(self, session, *args, **kwargs)
            session.commit()
            # TODO: Ask if user wants refresh?
            # For now we don't have any update methods so this shouldn't be needed
            return result

    return inner
