import { afterEach, describe, expect, it, vi } from 'vitest'

import { HttpControlPlaneClient } from './control-plane'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('HttpControlPlaneClient', () => {
  it('returns the operations projection unchanged from the bot-scoped upstream path', async () => {
    const projection = {
      scope: { platform: 'qq', botId: 'bot/42' },
      projections: [{
        surface: 'mcp_capability' as const,
        scope: { platform: 'qq', botId: 'bot/42' },
        revision: 'mcp-v2',
        evidenceMode: 'offline' as const,
        status: 'degraded' as const,
        facts: [],
        reasonCodes: ['health_snapshot_unavailable'],
        observedAt: '2026-08-14T13:00:00Z',
      }],
      mutations: [],
      generatedAt: '2026-08-14T13:00:00Z',
    }
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(projection), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const client = new HttpControlPlaneClient('http://control-plane.local')

    await expect(client.operations('operator-session', 'qq', 'bot/42')).resolves.toEqual(projection)
    expect(fetchMock).toHaveBeenCalledWith(
      'http://control-plane.local/v1/control-plane/qq/bots/bot%2F42/operations',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-Dududa-Operator-Session': 'operator-session' }),
      }),
    )
  })
})
