"""结构化日志（structlog + orjson），Decimal 自定义序列化。"""

from __future__ import annotations

import logging
import sys
from decimal import Decimal
from typing import Any

import orjson
import structlog


def _default(obj: Any) -> Any:
    """orjson 无法序列化的类型回退：Decimal → 字符串（禁止转 float）。"""
    if isinstance(obj, Decimal):
        return str(obj)
    return str(obj)


def _orjson_dumps(obj: Any, **_: Any) -> str:
    return orjson.dumps(obj, default=_default).decode("utf-8")


def configure_logging(level: int = logging.INFO) -> None:
    """初始化 structlog；重复调用安全。"""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(serializer=_orjson_dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> Any:
    """获取带名字的结构化 logger。"""
    return structlog.get_logger(name)
