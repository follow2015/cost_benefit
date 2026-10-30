"""接口层：HTTP 传输细节（FastAPI 路由、依赖注入、统一错误出口）。

组合根所在层：允许依赖 application / domain / shared / infrastructure，
把请求翻译成用例调用，再把结果翻译成 `{code, message, data}` 响应。
"""
