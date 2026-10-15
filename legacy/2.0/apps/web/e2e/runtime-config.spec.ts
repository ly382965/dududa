import { expect, test } from '@playwright/test'

test('API Key apply uses only revision and shows live state on narrow screens', async ({ page }) => {
  const status = { status: 'pending', savedRevision: 7, ready: true,
    message: '已保存，尚未应用到当前 Runtime', checkedAt: '', scope: 'dududa_only' }
  await page.route('**/api/api-keys', route => route.fulfill({ json: { schemaVersion: 1, revision: 7, pools: [] } }))
  await page.route('**/api/api-keys/runtime', route => route.fulfill({ json: status }))
  const requests: unknown[] = []
  await page.route('**/api/api-keys/runtime/apply', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: { ...status, status: 'applied', message: '已应用到当前 Dududa Runtime' } })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/api-keys')
  await expect(page.getByRole('heading', { name: 'API Key 池' })).toBeVisible()
  await expect(page.getByText('已保存，尚未应用到当前 Runtime', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '应用到 Runtime', exact: true }).click()
  await expect(page.getByText('已应用到当前 Dududa Runtime', { exact: true })).toBeVisible()
  expect(requests).toEqual([{ revision: 7 }])
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})
