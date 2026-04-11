"""通用装饰器。"""

from __future__ import annotations

import functools
import time
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


def timed(func: F) -> F:
    """计时装饰器：记录函数执行时间。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        logger.info("%s took %.3fs", func.__name__, elapsed)
        return result

    return wrapper  # type: ignore[return-value]


def retry(max_attempts: int = 3, delay: float = 1.0):
    """重试装饰器。"""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logger.warning(
                        "%s failed (attempt %d/%d): %s",
                        func.__name__,
                        attempt + 1,
                        max_attempts,
                        str(e),
                    )
                    time.sleep(delay)

        return wrapper  # type: ignore[return-value]

    return decorator
