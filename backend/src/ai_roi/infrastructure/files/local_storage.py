"""本地文件系统网关（`ports.SystemGateway` 的实现）。

用途：报告产物落盘、上传暂存等需要触碰磁盘的场景。
所有路径都被限制在 `base_dir` 之内（防 `..` 逃逸）；
未配置 base_dir 时退化为系统临时目录，行为对调用方透明。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from ai_roi.application.ports import SystemGateway


class LocalFileStorage(SystemGateway):
    """基于本地目录的文件网关（进程内单例即可，无状态）。"""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "ai-roi"

    def _resolve(self, path: str) -> Path:
        """把相对路径解析到 base_dir 内；绝对路径或逃逸路径一律拒绝。"""
        candidate = Path(path)
        if candidate.is_absolute():
            raise ValueError(f"仅允许 base_dir 内的相对路径：{path}")
        resolved = (self._base / candidate).resolve()
        base = self._base.resolve()
        if base != resolved and base not in resolved.parents:
            raise ValueError(f"路径越出 base_dir：{path}")
        return resolved

    def save(self, relative_path: str, data: bytes) -> str:
        """写入文件（自动建目录），返回规范化后的绝对路径。"""
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    def read(self, path: str) -> bytes:
        """读取文件字节。"""
        return self._resolve(path).read_bytes()

    def exists(self, path: str) -> bool:
        """判断文件是否存在。"""
        return self._resolve(path).exists()

    def delete(self, path: str) -> None:
        """删除文件（不存在时静默）。"""
        target = self._resolve(path)
        if target.exists():
            target.unlink()


_storage: Optional[LocalFileStorage] = None


def get_storage(base_dir: Optional[str] = None) -> LocalFileStorage:
    """进程内单例（首次调用时的 base_dir 生效；传 None 用配置/临时目录）。"""
    global _storage
    if _storage is None:
        if base_dir is None:
            from ai_roi.shared.config import settings

            base_dir = getattr(settings, "REPORT_ARTIFACT_DIR", "") or None
        _storage = LocalFileStorage(base_dir)
    return _storage


__all__ = ["LocalFileStorage", "get_storage"]
