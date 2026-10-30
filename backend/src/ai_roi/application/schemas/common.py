"""通用响应包装与分页。

统一响应体：`{code: "OK", message: "", data: <payload>}`，与前端 `src/api/client.ts` 的
拦截器约定一致（错误响应额外带 `error_code`）。
"""

from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一成功响应。"""

    code: str = "OK"
    message: str = ""
    data: Optional[T] = None

    @classmethod
    def ok(cls, data: Optional[T] = None, message: str = "") -> "ApiResponse[T]":
        """构造成功响应。"""
        return cls(code="OK", message=message, data=data)


class PageMeta(BaseModel):
    """分页元信息。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    total: int = Field(default=0, ge=0)

    @property
    def offset(self) -> int:
        """SQL OFFSET。"""
        return (self.page - 1) * self.page_size


class PageResponse(BaseModel, Generic[T]):
    """分页数据体。"""

    items: List[T] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)


class OkData(BaseModel):
    """无实体返回时的占位数据。"""

    ok: bool = True
    detail: Optional[Any] = None
