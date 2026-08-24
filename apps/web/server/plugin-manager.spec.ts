import { describe, expect, it, vi } from 'vitest'

import {
  HttpAstrBotPluginManagerClient,
  PluginManagerClientError,
  normalizeGithubRepository,
} from './plugin-manager'

describe('AstrBot plugin manager client', () => {
  it('maps runtime plugins and keeps the plugin API key server-side', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('X-API-Key')).toBe('plugin-only-secret')
      return new Response(JSON.stringify({
        status: 'ok',
        data: [{
          name: 'astrbot_plugin_demo',
          display_name: 'Demo',
          desc: 'A demo plugin',
          version: 'v1.0.0',
          author: 'tester',
          activated: true,
          reserved: false,
          root_dir_name: 'astrbot_plugin_demo',
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new HttpAstrBotPluginManagerClient('http://astrbot:6185/api/v1', 'plugin-only-secret')
    await expect(client.catalog()).resolves.toMatchObject({
      available: true,
      plugins: [{ id: 'astrbot_plugin_demo', displayName: 'Demo', activated: true }],
    })
    expect(JSON.stringify(await client.catalog())).not.toContain('plugin-only-secret')
    vi.unstubAllGlobals()
  })

  it('projects version warnings and rejects arbitrary remote URLs', async () => {
    const responses = [
      { status: 'ok', data: {} },
      {
        status: 'warning',
        message: '当前 AstrBot 版本不满足插件要求',
        data: { can_ignore: true },
      },
      { status: 'ok', data: { astrbot_plugin_demo: { error: 'unsupported' } } },
      { status: 'ok', message: '已移除失败插件', data: {} },
    ]
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const payload = responses.shift()
      expect(payload).toBeDefined()
      if (init?.method === 'DELETE') expect(String(_url)).toContain('/plugins/failed/astrbot_plugin_demo')
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new HttpAstrBotPluginManagerClient('http://astrbot:6185/api/v1', 'plugin-only-secret')
    await expect(client.installGithub('https://github.com/example/demo')).resolves.toMatchObject({
      status: 'warning',
      canIgnoreVersionCheck: true,
    })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(() => normalizeGithubRepository('https://127.0.0.1/plugin.zip')).toThrow(PluginManagerClientError)
    expect(() => normalizeGithubRepository('https://github.com/example/demo/releases/latest')).toThrow()
    vi.unstubAllGlobals()
  })

  it('reports an unconfigured key without calling AstrBot', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const client = new HttpAstrBotPluginManagerClient('http://astrbot:6185/api/v1', () => '')
    await expect(client.catalog()).resolves.toMatchObject({ available: false, plugins: [] })
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
