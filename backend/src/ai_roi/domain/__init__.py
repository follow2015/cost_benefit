"""领域层：计算引擎 + 参数校验 + 领域错误。

硬约束：本层仅依赖 Python 标准库与 decimal，禁止 import 任何 Web 框架、
数据库驱动或 IO 组件（import-linter 契约 L1 强制，见 backend/.importlinter）。
"""
