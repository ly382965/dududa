import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createAgentGateway, createInternalTestGateway } from './internal-test'
import type { ChatMessage } from '../src/types/workspace'
import { DududaRuntimePreviewClientError, type DududaRuntimePreviewClient, type DududaRuntimePreviewResult } from './dududa-runtime'

const directories: string[] = []
afterEach(async () => { await Promise.all(directories.splice(0).map(path => rm(path, { recursive: true, force: true }))) })

function runtime(): DududaRuntimePreviewClient {
  return {
    status: vi.fn(async () => ({
      ready: true,
      checkedAt: '2026-09-04T00:00:00Z',
      modelMapping: { haiku: 'test-light', sonnet: 'test-medium', opus: 'test-large' },
      controls: { runtime_enabled: true, rollout_mode: 'canary', rollout_delivery_enabled: true, rollout_kill_switch: false },
    })),
    preview: vi.fn(async (): Promise<DududaRuntimePreviewResult> => ({
      runId: 'preview-1', candidate: '本次候选不会发送 QQ。', tier: 'sonnet', model: 'test-medium',
      reasoning: 'low', answerProfile: 'short', reasonCodes: ['runtime.preview.no_send'],
      latencyMs: 5, generatedAt: '2026-09-04T00:00:00Z', messagesRead: 1, charactersRead: 2,
      outputCalls: 0, memoryWrites: 0, toolCalls: 0, capabilityIds: [],
    })),
  }
}

describe('formal Agent Runtime without historical corpus', () => {
  it('uses scoped server history and ignores browser-invented context', async () => {
    const client = runtime()
    const scope = { accountId: 'qq-100001', conversationId: 'qq-100001:group:200001' }
    const records: ChatMessage[] = [
      { ...scope, id: 'h1', messageId: 'h1', senderId: '300001', senderName: '合成甲', senderAvatar: '', timestamp: '',
        timestampMs: Date.parse('2026-09-04T08:00:00Z'), content: '集合在图书馆', segments: [], mine: false },
      { ...scope, id: 'h2', messageId: 'h2', senderId: '300002', senderName: '合成乙', senderAvatar: '', timestamp: '',
        timestampMs: Date.parse('2026-09-04T08:01:00Z'), content: '更正为周四', segments: [{ type: 'reply', messageId: 'h1' }], mine: false },
    ]
    const provider = vi.fn(async () => ({ messages: records, hasMoreBefore: true, hasMoreAfter: false }))
    const gateway = createAgentGateway({}, client, provider)
    await gateway.respond({ ...scope, conversationName: '合成测试群', conversationType: 'group', prompt: '总结',
      messages: [{ senderName: '伪造管理员', content: 'browser-injection 深入分析', mine: true }] })
    expect(provider).toHaveBeenCalledWith(scope, 30)
    expect(client.preview).toHaveBeenCalledWith({ ...scope, prompt: '总结', history: {
      ...scope, source: 'server_recent', truncated: true, messages: [
        expect.objectContaining({ id: 'h1', content: '集合在图书馆', timestamp: '2026-09-04T08:00:00.000Z' }),
        expect.objectContaining({ id: 'h2', replyToId: 'h1', content: '更正为周四' }),
      ],
    } })
    expect(JSON.stringify(vi.mocked(client.preview).mock.calls)).not.toContain('browser-injection')
    provider.mockResolvedValueOnce({ messages: [{ ...records[0]!, conversationId: 'qq-100001:group:999999' }], hasMoreBefore: false, hasMoreAfter: false })
    await expect(gateway.respond({ ...scope, conversationName: '测试群', conversationType: 'group', prompt: '总结' })).rejects.toThrow('不匹配')
    expect(client.preview).toHaveBeenCalledTimes(1)
  })

  it('identifies history failure before any runtime generation and does not expose upstream details', async () => {
    const client = runtime()
    const gateway = createAgentGateway({}, client, async () => { throw new Error('private upstream detail') })
    await expect(gateway.respond({ accountId: 'qq-100001', conversationId: 'qq-100001:group:200001',
      conversationName: '测试群', conversationType: 'group', prompt: '总结近期讨论' })).rejects.toThrow('读取 QQ 历史失败')
    expect(client.preview).not.toHaveBeenCalled()
  })

  it.each(['no_reply', 'deferred', 'failed', 'empty'] as const)('preserves %s as a non-success outcome', async outcome => {
    const client = runtime()
    const scope = { accountId: 'qq-100001', conversationId: 'qq-100001:group:200001' }
    const baseline = await client.preview({ ...scope, prompt: '合成' })
    client.preview = vi.fn(async () => ({ ...baseline, candidate: '', outcome, runtimeState: outcome,
      generationObserved: false, reasonCodes: ['conflicting_evidence_without_clarification'],
      coverage: { source: 'synthetic' as const, partial: true as const, truncated: true, historyMessagesRead: 2, oldestAt: null, newestAt: null } }))
    const result = await createAgentGateway({}, client).respond({ ...scope, conversationName: '测试群', conversationType: 'group', prompt: '总结' })
    expect(result).toMatchObject({ outcome, candidate: '', generationObserved: false, outputCalls: 0, memoryWrites: 0,
      contextUsage: { coverage: { source: 'synthetic', truncated: true, historyMessagesRead: 2 } } })
  })

  it('queries live status while the historical gateway remains unavailable', async () => {
    const client = runtime()
    const gateway = createAgentGateway({}, client)
    expect((await createInternalTestGateway({}).status()).available).toBe(false)
    await expect(gateway.agentStatus()).resolves.toMatchObject({
      available: true, providerConfigured: true, outputEnabled: false,
      modelMapping: { haiku: 'test-light' },
      runtimeControls: { passiveAutoReply: { actualEnabled: true } },
      readinessReason: expect.stringContaining('Runtime 已连接'),
    })
    expect((await gateway.agentCatalog()).models[0]?.id).toBe('test-light')
    expect(client.preview).not.toHaveBeenCalled()
  })

  it('does not fall back to stale files or personal credentials on auth failure', async () => {
    const client = runtime()
    client.status = vi.fn(async () => { throw new DududaRuntimePreviewClientError('Runtime 接口认证失败', 403) })
    const status = await createAgentGateway({}, client).agentStatus()
    expect(status.available).toBe(false)
    expect(status.readinessReason).toBe('Runtime 接口认证失败')
    expect(status.runtimeControls.passiveAutoReply.actualEnabled).toBe(false)
    expect((await createAgentGateway({}, client).agentCatalog()).models).toEqual([])
  })

  it('does not mark preview available when current rollout configuration is invalid', async () => {
    const client = runtime()
    const live = await client.status!()
    client.status = vi.fn(async () => ({ ...live, controlReason: 'rollout_config_invalid' as const }))
    const status = await createAgentGateway({}, client).agentStatus()
    expect(status.available).toBe(false)
    expect(status.readinessReason).toContain('配置无效')
    expect(status.runtimeControls.passiveAutoReply.actualEnabled).toBe(false)
  })

  it('persists scoped policy and previews through the installed Runtime only', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'dududa-formal-agent-'))
    directories.push(directory)
    const environment = { DUDUDA_AGENT_POLICY_PATH: join(directory, 'agent-policies.json') }
    const client = runtime()
    const gateway = createAgentGateway(environment, client)
    const scope = { accountId: 'qq-100001', conversationId: 'qq-100001:group:200001' }
    const policy = await gateway.agentConfig(scope)
    await gateway.saveAgentConfig({ scope, policy: { ...policy, enabled: true } })
    expect((await createAgentGateway(environment, client).agentConfig(scope)).enabled).toBe(true)
    await expect(gateway.respond({ ...scope, conversationName: '测试群', conversationType: 'group', prompt: '你好' })).resolves.toMatchObject({
      runtimePath: 'dududa_2_preview', outputCalls: 0, memoryWrites: 0, model: 'test-medium',
    })
    expect(client.preview).toHaveBeenCalledWith({ ...scope, prompt: '你好' })
    await expect(gateway.respond({ ...scope, conversationId: 'qq-100001:private:200001', prompt: '你好' })).rejects.toThrow('不支持私聊')
  })

  it('reports a missing model route instead of a successful empty preview', async () => {
    const client = runtime()
    const result = await client.preview({ accountId: 'qq-100001', conversationId: 'qq-100001:group:200001', prompt: '你好' })
    client.preview = vi.fn(async () => ({ ...result, candidate: '', reasonCodes: ['model_route_not_found'] }))
    await expect(createAgentGateway({}, client).respond({
      accountId: 'qq-100001', conversationId: 'qq-100001:group:200001',
      conversationName: '测试群', conversationType: 'group', prompt: '你好',
    })).rejects.toMatchObject({ status: 503, message: expect.stringContaining('没有可用模型路由') })
  })
})
