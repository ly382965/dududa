import { describe, expect, it, vi } from 'vitest'

import { HttpDududaRuntimePreviewClient } from './dududa-runtime'

describe('Dududa Runtime preview client', () => {
  it('calls the AstrBot plugin extension and preserves tool evidence', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe(
        'http://astrbot:6185/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime/preview',
      )
      expect(init?.headers).toMatchObject({ 'X-API-Key': 'plugin-key' })
      expect(JSON.parse(String(init?.body))).toEqual({
        accountId: 'qq-3296147894',
        conversationId: 'qq-3296147894:group:364894085',
        prompt: '查询评课社区吴天',
      })
      return new Response(JSON.stringify({
        status: 'ok',
        data: {
          runId: 'run-1',
          candidate: '已完成评课总结。',
          tier: 'sonnet',
          model: 'gpt-5.6-terra',
          reasoning: 'low',
          answerProfile: 'long',
          reasonCodes: ['runtime.preview.no_send'],
          latencyMs: 123,
          generatedAt: '2026-08-28T09:00:00Z',
          messagesRead: 1,
          charactersRead: 9,
          outputCalls: 0,
          memoryWrites: 0,
          toolCalls: 1,
          capabilityIds: ['icourse.public-query.v2'],
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const client = new HttpDududaRuntimePreviewClient(
      'http://astrbot:6185/api/v1',
      'plugin-key',
      fetchImpl as typeof fetch,
    )

    await expect(client.preview({
      accountId: 'qq-3296147894',
      conversationId: 'qq-3296147894:group:364894085',
      prompt: '查询评课社区吴天',
    })).resolves.toMatchObject({
      runId: 'run-1',
      toolCalls: 1,
      capabilityIds: ['icourse.public-query.v2'],
      outputCalls: 0,
    })
  })
})
