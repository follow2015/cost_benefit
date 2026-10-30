"""应用配置（pydantic-settings）。

全局口径默认值在此固化：币种 CNY（本位币）、税前口径（taxed=false），
与前端 `src/calc-engine/decimalConfig.ts` 的 DEFAULT_CONVENTIONS 一致。
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource


class _NoJsonEnvSource(EnvSettingsSource):
    """环境源：跳过复杂字段的 JSON 自动解析。

    pydantic-settings 默认对 List/Dict 字段无条件 json.loads，
    导致 `a,b,c` 形式的 CORS_ORIGINS 在校验器之前崩溃。
    本项目唯一复杂字段是 CORS_ORIGINS，其 before-validator 负责按逗号拆分。
    """

    def decode_complex_value(self, field_name, field, value):
        return value


class _NoJsonDotEnvSource(DotEnvSettingsSource):
    def __init__(self, settings_cls, env_file=None, env_file_encoding=None, **kwargs):
        super().__init__(
            settings_cls,
            env_file=env_file,
            env_file_encoding=env_file_encoding,
            **kwargs,
        )

    def decode_complex_value(self, field_name, field, value):
        return value


_INSECURE_JWT_SECRET = "change-me-in-production-please-32chars-min"


class Settings(BaseSettings):
    """后端运行时配置。所有字段均有默认值，保证无 .env 亦可启动（除 DB 连接）。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    APP_NAME: str = "ai-roi-calculator"
    APP_ENV: str = "dev"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://roi:roi_pwd@localhost:5432/ai_roi"
    DATABASE_URL_SYNC: str = ""
    DB_ECHO: bool = False
    DB_SCHEMA: str = "app"

    POSTGRESQL_HOST: str = ""
    POSTGRESQL_PORT: int = 5432
    POSTGRESQL_USER: str = ""
    POSTGRESQL_PASSWORD: str = ""
    POSTGRESQL_DATABASE: str = ""

    JWT_SECRET: str = "change-me-in-production-please-32chars-min"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 20160

    LOGIN_RATE_MAX_FAILURES: int = 5
    LOGIN_RATE_WINDOW_SECONDS: int = 300

    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    TRUSTED_HOSTS: List[str] = Field(default_factory=lambda: ["*"])

    ENABLE_API_DOCS: Optional[bool] = None

    SEED_DEMO_PASSWORD: str = ""
    SEED_DEMO_EMAIL: str = "demo@airoi.dev"

    DEFAULT_CURRENCY: str = "CNY"
    DEFAULT_TAXED: bool = False

    FX_USD_CNY: str = "6.68"

    INFERENCEX_SYNC_ENABLED: bool = True
    INFERENCEX_SYNC_INTERVAL_DAYS: int = 7
    INFERENCEX_BASE_URL: str = "https://inferencex.semianalysis.com"
    INFERENCEX_FX_USD_CNY: str = ""

    @property
    def inferencex_fx(self) -> str:
        """InferenceX 折算汇率：优先旧配置项，否则用统一口径。"""
        return self.INFERENCEX_FX_USD_CNY or self.FX_USD_CNY

    REDIS_URL: str = ""
    REDIS_HOST: str = ""
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 20

    @field_validator("CORS_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """支持 `a,b,c` 形式或 JSON 数组形式的环境变量。"""
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                import json

                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """使用关闭 JSON 解析的环境源，使逗号分隔值可被校验器处理。

        ⚠️ 已知边界：本方法自建 DotEnvSettingsSource，**绕过了** `BaseSettings`
        的 `_env_file` 参数机制（该参数由 `__init__` 消费，不会留在 init_kwargs 里，
        这里取不到）。因此 `Settings(_env_file=None)` 在有 `backend/.env` 的机器上
        仍会读入 .env —— 想彻底隔离 .env 的调用方（如安全基线测试）请改在空临时
        目录里构造，别指望这个参数。
        """
        return (
            init_settings,
            _NoJsonEnvSource(settings_cls),
            _NoJsonDotEnvSource(
                settings_cls,
                env_file=cls.model_config.get("env_file"),
                env_file_encoding=cls.model_config.get("env_file_encoding"),
            ),
            file_secret_settings,
        )

    @property
    def sync_database_url(self) -> str:
        """Alembic 使用的同步 URL（缺省由异步 URL 派生）。"""
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        return self.DATABASE_URL.replace("+asyncpg", "").replace(
            "postgresql://", "postgresql://"
        )

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        """提供 PostgreSQL_* 显式连接参数时，组合出异步 DATABASE_URL（覆盖默认值）。"""
        if self.POSTGRESQL_HOST and self.POSTGRESQL_USER and self.POSTGRESQL_DATABASE:
            pwd = f":{self.POSTGRESQL_PASSWORD}" if self.POSTGRESQL_PASSWORD else ""
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRESQL_USER}{pwd}"
                f"@{self.POSTGRESQL_HOST}:{self.POSTGRESQL_PORT}/{self.POSTGRESQL_DATABASE}"
            )
        return self

    @model_validator(mode="after")
    def _assemble_redis_url(self) -> "Settings":
        """未显式给 REDIS_URL 但提供了 REDIS_* 时，组合出连接串。"""
        if not self.REDIS_URL and self.REDIS_HOST:
            pwd = f":{self.REDIS_PASSWORD}" if self.REDIS_PASSWORD else ""
            self.REDIS_URL = (
                f"redis://{pwd}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )
        return self

    @model_validator(mode="after")
    def _guard_insecure_defaults(self) -> "Settings":
        """生产环境不允许沿用例子里 JWT 密钥。

        这个默认值在仓库、文档和 .env.example 里各出现一次，照着复制粘贴是常态。
        留着它等于把「签发任意租户 token」的能力公开——HS256 的密钥就是签名凭据。
        dev 不管（本地本来就不需要），prod 直接拒绝启动，让问题在部署时暴露，
        而不是在被人登进来之后才发现。
        """
        env = self.APP_ENV.strip().lower()
        if env in {"prod", "production"} and self.JWT_SECRET == _INSECURE_JWT_SECRET:
            raise ValueError(
                "APP_ENV=prod 时 JWT_SECRET 仍是示例默认值：任何人都能伪造 token。"
                ' 生成一个：python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return self

    @property
    def api_docs_enabled(self) -> bool:
        """是否暴露 `/docs`、`/redoc` 与 `/openapi.json`。

        显式配置优先；否则只在 dev/local/test 打开 —— 文档页把全部路径、参数、
        鉴权方式摊开，对外站点没有保留它的理由（默认值仍向后兼容本地开发）。
        """
        if self.ENABLE_API_DOCS is not None:
            return self.ENABLE_API_DOCS
        return self.APP_ENV.strip().lower() in {"dev", "local", "test"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局唯一配置实例（进程内缓存）。"""
    return Settings()


settings: Settings = get_settings()
