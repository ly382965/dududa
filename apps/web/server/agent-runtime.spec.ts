import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createAgentGateway, createInternalTestGateway } from './internal-test'
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
})
