import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:4174',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    channel: 'chrome',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: true,
    timeout: 30_000,
    env: {
      ...process.env,
      VITE_PORT: '4174',
      DUDUDA_WEB_INTERNAL_PORT: '8180',
      DUDUDA_ONEBOT_TOKEN: 'playwright-only-onebot-token-32-chars',
    },
  },
})
