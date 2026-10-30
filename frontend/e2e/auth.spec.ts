import { test, expect } from '@playwright/test';
import { clickButton, login, EMAIL } from './support';

/**
 * 鉴权冒烟：错误密码被拒 + 正确凭据登录后进入工作台。
 * 对接真实后端（VITE_API_BASE 直连，默认 http://localhost:8000；需后端 CORS 放行 5173）。
 */
test.describe('鉴权', () => {
  test('错误密码返回错误提示且不进入工作台', async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder('邮箱').fill(EMAIL);
    await page.getByPlaceholder('密码').fill('wrong-password');
    await clickButton(page, '登录');
    // 错误提示出现（AntD Alert），且不跳转
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('正确凭据登录后跳转工作台', async ({ page }) => {
    await login(page);
    await expect(page.getByText('新建测算方案').first()).toBeVisible();
  });

  /**
   * 回归护栏：登录页曾经把「demo@airoi.dev / demo123456」明文印在页面上，
   * 还把两个值预填进输入框 —— 等于给每个能打开页面的人发一份 owner 凭据。
   *
   * 这条断言存在的意义是：这类回归在功能上「更好用」（省得手输），
   * 代码评审很容易放过，只有测试能拦住。构建产物是静态文件，
   * 一旦把密码写回前端，改后端也救不回来。
   */
  test('登录页不预填凭据，页面里也不出现密码', async ({ page }) => {
    await page.goto('/login');

    await expect(page.getByPlaceholder('邮箱')).toHaveValue('');
    await expect(page.getByPlaceholder('密码')).toHaveValue('');

    const body = await page.locator('body').innerText();
    expect(body).not.toContain('demo123456');
    expect(body).not.toContain('演示账号：');

    // 连源码里也不该留（dev server 会把模块原样吐出，等价于公开源码）
    const html = await page.content();
    expect(html).not.toContain('demo123456');
  });
});
