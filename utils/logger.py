"""结构化日志配置。"""

from __future__ import annotations

import logging
import sys


def setup_logger(
    name: str = "myquant",
    level: int = logging.INFO,
) -> logging.Logger:
    """创建并配置 logger。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
