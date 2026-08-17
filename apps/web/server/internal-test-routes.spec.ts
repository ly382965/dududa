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
      reasoning: 'medium' as const,
      answerProfile: 'medium' as const,
      replyIntensity: 'normal' as const,
      contextLength: 'standard' as const,
      groupChatStyle: 'natural' as const,
      contextUsage: { messageLimit: 30, characterLimit: 18_000, messagesRead: 0, charactersRead: 0 },
      effectiveSelection: {
        scope: { accountId: 'default', conversationId: 'group-1' },
        policySource: 'default' as const,
        modelTier: 'sonnet' as const,
        model: 'gpt-5.6-terra',
        reasoning: 'medium' as const,
        answerProfile: 'medium' as const,
        replyIntensity: 'normal' as const,
        contextLength: 'standard' as const,
        groupChatStyle: 'natural' as const,
        contextUsage: { messageLimit: 30, characterLimit: 18_000, messagesRead: 0, charactersRead: 0 },
        plugins: {},
      },
      reasonCodes: ['policy.default'],
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
        runtimeControls: {
          passiveAutoReply: {
            actualEnabled: false,
            state: 'disabled',
            rolloutMode: 'off',
            deliveryEnabled: false,
            killSwitch: true,
            summary: '被动自动回复当前实际关闭。',
          },
          proactiveGroupParticipation: {
            actualEnabled: false,
            state: 'shadow',
            stage: 'probe_shadow',
            deliveryEnabled: false,
            summary: '主动参与当前只有 Probe Shadow。',
          },
        },
        warnings: ['NO SEND'],
      }),
      agentCatalog: async () => ({
        agent: { id: 'dududa', displayName: '嘟嘟哒' },
        selectionModes: ['adaptive', 'preferred', 'locked'],
        pluginModes: ['off', 'auto', 'on', 'locked'],
        models: [],
        reasoningLevels: ['low', 'medium', 'high'],
        answerProfiles: ['short', 'medium', 'long'],
        replyIntensities: ['quiet', 'normal', 'active'],
        contextLengths: [
          { id: 'compact', messageLimit: 12, characterLimit: 6_000 },
          { id: 'standard', messageLimit: 30, characterLimit: 18_000 },
          { id: 'extended', messageLimit: 60, characterLimit: 36_000 },
        ],
        groupChatStyles: ['restrained', 'natural', 'lively', 'technical'],
        replyIntensityNotice: '候选决策初值；当前运行态为 NO SEND，不控制真实消息发送概率。',
        plugins: [],
        policyDefaults: {
          enabled: true,
          modelTier: { mode: 'adaptive', preferred: 'sonnet', allowed: ['haiku', 'sonnet', 'opus'] },
          reasoning: { mode: 'adaptive', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
          answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
          replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
          contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['compact', 'standard', 'extended'] },
          groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['restrained', 'natural', 'lively', 'technical'] },
          plugins: {},
        },
      }),
      agentConfig: async () => ({
        schemaVersion: 1,
        scope: { accountId: 'account-1', conversationId: 'group-1' },
        enabled: true,
        modelTier: { mode: 'adaptive', preferred: 'sonnet', allowed: ['haiku', 'sonnet', 'opus'] },
        reasoning: { mode: 'adaptive', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
        answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
        replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
        contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['compact', 'standard', 'extended'] },
        groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['restrained', 'natural', 'lively', 'technical'] },
        plugins: {},
      }),
      saveAgentConfig: async (body) => ({
        schemaVersion: 1,
        scope: body.scope as { accountId: string; conversationId: string },
        enabled: true,
        modelTier: { mode: 'adaptive', preferred: 'sonnet', allowed: ['haiku', 'sonnet', 'opus'] },
        reasoning: { mode: 'adaptive', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
        answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
        replyIntensity: { mode: 'adaptive', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
        contextLength: { mode: 'adaptive', preferred: 'standard', allowed: ['compact', 'standard', 'extended'] },
        groupChatStyle: { mode: 'adaptive', preferred: 'natural', allowed: ['restrained', 'natural', 'lively', 'technical'] },
        plugins: {},
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
    await expect(status.json()).resolves.toMatchObject({
      available: true,
      outputEnabled: false,
      runtimeControls: {
        passiveAutoReply: {
          actualEnabled: false,
          rolloutMode: 'off',
          deliveryEnabled: false,
          killSwitch: true,
        },
        proactiveGroupParticipation: {
          actualEnabled: false,
          stage: 'probe_shadow',
          deliveryEnabled: false,
        },
      },
    })

    const catalog = await fetch(`${baseUrl}/api/internal-test/agent/catalog`)
    expect(catalog.status).toBe(200)
    await expect(catalog.json()).resolves.toMatchObject({ agent: { id: 'dududa' } })

    const config = await fetch(`${baseUrl}/api/internal-test/agent/config?accountId=account-1&conversationId=group-1`)
    expect(config.status).toBe(200)
    await expect(config.json()).resolves.toMatchObject({ scope: { accountId: 'account-1', conversationId: 'group-1' } })

    const configForbidden = await fetch(`${baseUrl}/api/internal-test/agent/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: { accountId: 'account-1', conversationId: 'group-1' } }),
    })
    expect(configForbidden.status).toBe(403)

    const configSaved = await fetch(`${baseUrl}/api/internal-test/agent/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Origin: baseUrl },
      body: JSON.stringify({ scope: { accountId: 'account-1', conversationId: 'group-1' } }),
    })
    expect(configSaved.status).toBe(200)

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
