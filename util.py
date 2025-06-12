from functools import wraps
import inspect
import os
import sys
from typing import Awaitable, Callable, Concatenate, ParamSpec, TypeVar

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


def transactional(
    m: Callable[Concatenate[object, Session, P], R | Awaitable[R]],
) -> Callable[Concatenate[object, P], R | Awaitable[R]]:
    """Convenient wrapper for passing a session into your method and commiting any changes you
    make.
    """

    @wraps(m)
    def inner(self: object, *args: P.args, **kwargs: P.kwargs) -> R | Awaitable[R]:
        engine = get_context().fastmcp.db_engine
        with Session(engine) as session:

            def commit(result: R) -> R:
                session.commit()
                # TODO: Ask if user wants refresh?
                # For now we don't have any update methods so this shouldn't be needed
                return result

            if inspect.iscoroutinefunction(m):

                async def async_inner() -> R:
                    return commit(await m(self, session, *args, **kwargs))

                return async_inner()
            else:
                return commit(m(self, session, *args, **kwargs))

    return inner
