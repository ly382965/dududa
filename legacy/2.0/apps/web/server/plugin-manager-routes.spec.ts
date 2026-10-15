import type { AddressInfo } from 'node:net'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createDududaServer } from './app'
import type { PluginManagerClient } from './plugin-manager'
import { OneBotHub } from './onebot-hub'

const servers: Array<ReturnType<typeof createDududaServer>> = []

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))))
})

async function fixture() {
  const installGithub = vi.fn(async () => ({ status: 'ok' as const, message: '安装成功' }))
  const installUpload = vi.fn(async () => ({ status: 'ok' as const, message: '安装成功' }))
  const pluginManager: PluginManagerClient = {
    catalog: async () => ({
      available: true,
      plugins: [{
        id: 'astrbot_plugin_demo',
        name: 'astrbot_plugin_demo',
        displayName: 'Demo',
        description: 'Demo plugin',
        version: 'v1.0.0',
        author: 'tester',
        activated: true,
        reserved: false,
      }],
    }),
    installGithub,
    installUpload,
  }
  const server = createDududaServer({
    hub: new OneBotHub({ token: 'test-only-onebot-token-32-characters' }),
    publicDir: '/tmp/dududa-web-does-not-exist',
    pluginManager,
  })
  servers.push(server)
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  return { baseUrl, installGithub, installUpload }
}

describe('runtime plugin manager routes', () => {
  it('lists runtime plugins and requires same-origin for installation', async () => {
    const { baseUrl, installGithub } = await fixture()
    const catalog = await fetch(`${baseUrl}/api/plugins/runtime`)
    await expect(catalog.json()).resolves.toMatchObject({
      available: true,
      plugins: [{ id: 'astrbot_plugin_demo', activated: true }],
    })

    const forbidden = await fetch(`${baseUrl}/api/plugins/install/github`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repository: 'https://github.com/example/demo' }),
    })
    expect(forbidden.status).toBe(403)
    expect(installGithub).not.toHaveBeenCalled()

    const installed = await fetch(`${baseUrl}/api/plugins/install/github`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ repository: 'https://github.com/example/demo' }),
    })
    expect(installed.status).toBe(200)
    expect(installGithub).toHaveBeenCalledWith('https://github.com/example/demo', false)
  })

  it('accepts one ZIP upload and forwards the explicit compatibility override', async () => {
    const { baseUrl, installUpload } = await fixture()
    const form = new FormData()
    form.append(
      'file',
      new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00])], { type: 'application/zip' }),
      'astrbot_plugin_demo.zip',
    )
    const response = await fetch(`${baseUrl}/api/plugins/install/upload?ignoreVersionCheck=true`, {
      method: 'POST',
      headers: { Origin: baseUrl },
      body: form,
    })
    expect(response.status).toBe(200)
    expect(installUpload).toHaveBeenCalledWith(
      expect.objectContaining({ fileName: 'astrbot_plugin_demo.zip', size: 5 }),
      true,
    )
  })
})
