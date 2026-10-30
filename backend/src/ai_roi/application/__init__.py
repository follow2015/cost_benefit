"""应用层：用例编排 + 端口定义。

只依赖 domain 与 shared；通过 `ports` 声明对基础设施的需求，
由组合根（`ai_roi.main` / `interfaces.api.deps`）注入具体实现。
"""
