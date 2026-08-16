import type { AddressInfo } from 'node:net'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createDududaServer } from './app'
import type { InternalTestGateway } from './internal-test'
import { OneBotHub } from './onebot-hub'

const servers: Array<ReturnType<typeof createDududaServer>> = []

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))))
})

describe('internal-test agent routes', () => {
  it('reports runtime status and returns a same-origin no-send candidate', async () => {
    const respond = vi.fn(async () => ({
      runId: 'run-1',
      candidate: '候选回答',
      tier: 'sonnet' as const,
      model: 'gpt-5.6-terra',
      answerProfile: 'medium' as const,
      latencyMs: 12,
      generatedAt: '2026-08-16T10:00:00.000Z',
      outputCalls: 0 as const,
      memoryWrites: 0 as const,
      toolCalls: 0 as const,
    }))
    const internalTest: InternalTestGateway = {
      status: async () => ({
        available: true,
        evidenceMode: 'private_silver_shadow',
        outputEnabled: false,
        providerConfigured: true,
        sampleCount: 0,
        modelMapping: { haiku: 'luna', sonnet: 'terra', opus: 'sol' },
        warnings: [],
      }),
      samples: async () => ({ items: [], total: 0, offset: 0, limit: 24 }),
      progress: async () => ({ total: 0, evaluated: 0, pending: 0, accepted: 0, rejected: 0, needsReview: 0 }),
      generate: async () => { throw new Error('not used') },
      feedback: async () => { throw new Error('not used') },
      agentStatus: async () => ({
        available: true,
        providerConfigured: true,
        outputEnabled: false,
        modelMapping: { haiku: 'luna', sonnet: 'terra', opus: 'sol' },
        warnings: ['NO SEND'],
      }),
      respond,
    }
    const hub = new OneBotHub({ token: 'test-only-onebot-token-32-characters' })
    const server = createDududaServer({ hub, publicDir: '/tmp/dududa-web-does-not-exist', internalTest })
    servers.push(server)
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`

    const status = await fetch(`${baseUrl}/api/internal-test/agent/status`)
    expect(status.status).toBe(200)
    await expect(status.json()).resolves.toMatchObject({ available: true, outputEnabled: false })

    const requestBody = {
      conversationId: 'group-1',
      conversationName: '测试群',
      prompt: '回复这段对话',
      messages: [],
    }
    const forbidden = await fetch(`${baseUrl}/api/internal-test/agent/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })
    expect(forbidden.status).toBe(403)

    const response = await fetch(`${baseUrl}/api/internal-test/agent/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify(requestBody),
    })
    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toMatchObject({
      candidate: '候选回答',
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    })
    expect(respond).toHaveBeenCalledWith(requestBody)
  })
})
