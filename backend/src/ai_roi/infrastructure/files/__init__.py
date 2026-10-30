"""文件系统适配器：xlsx 清单读取、本地存储网关。

对应 `ai_roi.application.ports.SystemGateway` 与 BOM 行读取端口；
应用层不直接触碰 openpyxl / 磁盘路径。
"""

from ai_roi.infrastructure.files.bom_xlsx import (
    parse_network_bom,
    read_bom_rows,
)
from ai_roi.infrastructure.files.local_storage import (
    LocalFileStorage,
    get_storage,
)

__all__ = [
    "parse_network_bom",
    "read_bom_rows",
    "LocalFileStorage",
    "get_storage",
]
