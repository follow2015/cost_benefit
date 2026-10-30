"""安全基线：配置默认值与部署配置的回归护栏。

这些断言锁的是「默认值必须安全」，而不是某个功能的行为：

- 生产环境不能沿用仓库里的示例 JWT 密钥（否则谁都能自己签 token）；
- API 文档默认不对外（文档页等于公开全部路径与鉴权方式）；
- 演示账号密码不再有硬编码来源；
- nginx 的安全头只能写在片段里，否则会被 location 的 add_header 静默吞掉。

nginx 那两条是文本断言，看着不优雅，但它们是唯一能在改配置时立刻发现
「安全头又被写回 server 层」的办法 —— 这类问题在浏览器里看不出来，
只有抓响应头才发现，而没人会每次改配置都去抓。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from ai_roi.shared import config as config_mod
from ai_roi.shared.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "nginx" / "cost_benefit.conf"
SNIPPET_DIR = REPO_ROOT / "deploy" / "nginx" / "snippets"


def _settings(**overrides: object) -> Settings:
    """构造一份**真正不读 .env** 的配置，避免本机环境影响断言。

    ⚠️ 不能用 `Settings(_env_file=None)`：`config.Settings.settings_customise_sources`
    自建了 DotEnvSettingsSource，绕过了 `BaseSettings` 的 `_env_file` 机制（该参数在
    `__init__` 里就被消费掉），所以本机只要存在 `backend/.env`，密钥照样被读进来 ——
    实测后果是「生产密钥守卫」在有 .env 的开发机上静默不触发，而在没有 .env 的 CI 上
    碰巧通过：测试想锁的东西恰好没锁住。

    改为在**空临时目录**里构造：`env_file` 是相对路径（".env"），那里找不到文件。
    """
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            return Settings(**overrides)  # type: ignore[arg-type]
        finally:
            os.chdir(cwd)


class TestApiDocsExposure:
    def test_dev_exposes_docs_by_default(self) -> None:
        assert _settings(APP_ENV="dev").api_docs_enabled is True

    @pytest.mark.parametrize("env", ["prod", "production", "staging"])
    def test_non_dev_hides_docs_by_default(self, env: str) -> None:
        assert _settings(APP_ENV=env, JWT_SECRET="k" * 48).api_docs_enabled is False

    def test_explicit_override_wins_both_ways(self) -> None:
        assert _settings(APP_ENV="prod", JWT_SECRET="k" * 48, ENABLE_API_DOCS=True).api_docs_enabled
        assert not _settings(APP_ENV="dev", ENABLE_API_DOCS=False).api_docs_enabled


class TestJwtSecretGuard:
    def test_prod_rejects_repository_default(self) -> None:
        with pytest.raises(ValueError, match="JWT_SECRET"):
            _settings(APP_ENV="prod")

    def test_prod_allows_replaced_secret(self) -> None:
        assert _settings(APP_ENV="prod", JWT_SECRET="x" * 48).APP_ENV == "prod"

    def test_dev_tolerates_default(self) -> None:
        assert _settings(APP_ENV="dev").JWT_SECRET


class TestTrustedHosts:
    def test_default_is_permissive_for_backward_compat(self) -> None:
        assert _settings().TRUSTED_HOSTS == ["*"]

    def test_comma_separated_env_value_is_split(self) -> None:
        parsed = _settings(TRUSTED_HOSTS="roi.example.com, 127.0.0.1")
        assert parsed.TRUSTED_HOSTS == ["roi.example.com", "127.0.0.1"]


class TestSeedPassword:
    def test_generates_random_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.seed import GENERATED_PASSWORD_BYTES, resolve_password

        monkeypatch.setattr(config_mod.settings, "SEED_DEMO_PASSWORD", "")
        password, origin, must_show = resolve_password()

        assert len(password) >= GENERATED_PASSWORD_BYTES
        assert "随机" in origin
        assert must_show is True

    def test_uses_env_value_and_does_not_echo_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.seed import resolve_password

        monkeypatch.setattr(config_mod.settings, "SEED_DEMO_PASSWORD", "S3cure-Passw0rd-2026")
        password, origin, must_show = resolve_password()

        assert password == "S3cure-Passw0rd-2026"
        assert "环境变量" in origin
        assert must_show is False

    def test_rejects_short_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.seed import MIN_PASSWORD_LENGTH, resolve_password

        monkeypatch.setattr(config_mod.settings, "SEED_DEMO_PASSWORD", "short")
        with pytest.raises(SystemExit, match=str(MIN_PASSWORD_LENGTH)):
            resolve_password()

    def test_random_passwords_differ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.seed import resolve_password

        monkeypatch.setattr(config_mod.settings, "SEED_DEMO_PASSWORD", "")
        assert resolve_password()[0] != resolve_password()[0]

    def test_dsn_is_masked(self) -> None:
        from scripts.seed import mask_dsn

        masked = mask_dsn("postgresql+asyncpg://roi:roi_pwd@localhost:5432/ai_roi")
        assert "roi_pwd" not in masked
        assert "roi:***@localhost" in masked


class TestNginxSecurityHeaders:
    """安全头必须集中在片段里，且每个 location 都要 include。

    背景：nginx 的 add_header 一旦在某个 location 出现，就**完全**不继承上层。
    原配置把三个头写在 server 层，而 /assets/ 与 = /index.html 各自加了
    Cache-Control —— 于是这两个 location 静默丢掉了全部安全头，恰好是静态资源
    与入口 HTML。实测确认过（curl -I 抓不到 X-Content-Type-Options）。
    """

    def test_config_file_exists(self) -> None:
        assert NGINX_CONF.is_file(), "部署配置副本缺失，改动无法版本化"

    def test_headers_live_only_in_snippets(self) -> None:
        text = NGINX_CONF.read_text(encoding="utf-8")
        forbidden = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Strict-Transport-Security",
            "Content-Security-Policy",
        ]
        for name in forbidden:
            assert f"add_header {name}" not in text, (
                f"{name} 被写回了站点配置。它必须只在 snippets/ 里定义一次并由 location "
                "include，否则其它 location 会静默丢失该头。"
            )

    def test_every_location_includes_snippet(self) -> None:
        lines = NGINX_CONF.read_text(encoding="utf-8").splitlines()
        total_locations = 0
        covered = 0
        missing: list[str] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("location "):
                continue
            total_locations += 1
            window = lines[idx : idx + 5]
            if any("include C:/nginx/conf/snippets/security-headers" in w for w in window):
                covered += 1
                continue
            if "8081" in "\n".join(lines[max(0, idx - 60) : idx]):
                continue
            missing.append(stripped)

        assert not missing, f"这些 location 没 include 安全头片段：{missing}"

        assert total_locations - covered == 3, (
            f"location 共 {total_locations} 个、带头 {covered} 个，"
            "差值应恰好等于调试站的 3 个；差值变大说明有生产 location 漏了 include，"
            "变小说明放行逻辑把生产 location 也放过去了。"
        )

    def test_snippets_define_expected_headers(self) -> None:
        http = (SNIPPET_DIR / "security-headers.conf").read_text(encoding="utf-8")
        https = (SNIPPET_DIR / "security-headers-hsts.conf").read_text(encoding="utf-8")

        for name in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
            assert name in http
            assert name in https
        assert "Strict-Transport-Security" not in http
        assert "Strict-Transport-Security" in https
