"""AI 算力投资经济性测算平台 ·  redesign 主包（六边形架构）。

分层（依赖方向单向：interfaces → application → domain ← infrastructure）：
- domain/        纯领域层（纯函数 + Decimal，禁框架/IO/DB）；
- application/   用例编排与端口协议（Phase 2）；
- infrastructure/ 技术实现（DB/Redis/安全/文件，Phase 2）；
- interfaces/    HTTP 接口层（Phase 2）；
- shared/        跨层共享原语（Phase 2）。
"""
