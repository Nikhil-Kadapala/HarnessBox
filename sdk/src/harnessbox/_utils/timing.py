"""Timing utilities for performance instrumentation."""

import time
import logging
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def timed_operation(operation_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to measure and log operation timing.

    Usage:
        @timed_operation("git_clone")
        async def clone_repo(self, ...):
            ...

    Logs: "{operation_name} took {duration:.2f}s"
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start
                logger.info(f"{operation_name} took {duration:.2f}s")
                return result
            except Exception as e:
                duration = time.time() - start
                logger.error(f"{operation_name} failed after {duration:.2f}s: {e}")
                raise

        return wrapper  # type: ignore

    return decorator
