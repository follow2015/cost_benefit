"""外部数据源适配器（HTTP 客户端）。

本包只负责「拿到原始数据」，不含解析与落库逻辑：
- 解析/归一化 → ``ai_roi.domain.benchmark``
- 写入/合并   → ``ai_roi.application.use_cases``
"""

from ai_roi.infrastructure.collectors.inferencex import InferencexClient

__all__ = ["InferencexClient"]
