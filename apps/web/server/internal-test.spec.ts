import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createInternalTestGateway, FileInternalTestGateway } from './internal-test'

const temporaryDirectories: string[] = []

async function fixtureRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'dududa-internal-test-'))
  temporaryDirectories.push(root)
  await mkdir(join(root, 'demo'), { recursive: true })
  const projection = {
    generated_at: '2026-08-16T08:00:00.000Z',
    warnings: ['PRIVATE DEVELOPMENT DATA', 'SILVER, NOT GOLD', 'NO SEND'],
    windows: [
      {
        window_id: 'window-1',
        primary_bucket: 'short_chat',
        buckets: ['short_chat'],
        messages: [
          { message_ref: 'message-1', sender_ref: 'identity-1', text: '今天有什么安排？' },
          { message_ref: 'message-2', sender_ref: 'identity-2', text: '下午一起讨论项目。' },
        ],
        silver: { need_tools: false, semantic_complexity: 'medium', answer_profile: 'medium' },
        student: {
          need_tools: { label: false, confidence: 0.8 },
          semantic_complexity: { label: 'low', confidence: 0.6 },
          answer_profile: { label: 'short', confidence: 0.7 },
        },
        tier_preview: { selected_tier: 'sonnet', production_route: false },
      },
      {
        window_id: 'window-2',
        primary_bucket: 'ordinary_qa',
        buckets: ['ordinary_qa'],
        messages: [{ message_ref: 'message-3', sender_ref: 'identity-3', text: '这个概念是什么意思？' }],
        silver: { need_tools: false, semantic_complexity: 'low', answer_profile: 'short' },
        tier_preview: { selected_tier: 'haiku', production_route: false },
      },
    ],
  }
  await writeFile(
    join(root, 'demo/index.html'),
    `<script id="demo-data" type="application/json">${JSON.stringify(projection)}</script>`,
  )
  return root
}

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})

describe('internal-test gateway', () => {
  it('exposes a no-send agent runtime and returns a routed candidate for live workspace context', async () => {
    const root = await fixtureRoot()
    const providerRequest = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).toMatchObject({
        model: 'custom-sol',
        max_output_tokens: 1_200,
        reasoning: { effort: 'high' },
        store: false,
      })
      expect(String(body.input)).toContain('群成员：下午把接口联调一下')
      expect(String(body.input)).toContain('操作员指令：\n完整分析当前架构并给出讨论建议')
      expect(String(body.instructions)).toContain('不要调用工具')
      expect(String(body.instructions)).toContain('不要宣告、复述或刻意表演人设')
      expect(String(body.instructions)).toContain('默认简洁，不抢话，不逐条复述已有聊天')
      expect(String(body.instructions)).toContain('技术问题先给结论，再补足真正有用的步骤')
      expect(String(body.instructions)).toContain('技术讨论中优先使用准确术语和清晰结构')
      expect(String(body.instructions)).toContain('不要在回答中谈论或罗列人格规则')
      expect(String(body.instructions)).toContain('不要模仿某个具体群成员')
      expect(String(body.instructions)).toContain('不得改变事实、权限、任务要求或安全边界')
      expect(String(body.instructions)).not.toContain('warm、cute、clear')
      expect(String(body.instructions)).not.toContain('避免模式')
      return new Response(JSON.stringify({ output_text: '建议先确认接口契约，再按主链路完成一次联调。' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      models: { opus: 'custom-sol' },
      fetchImpl: providerRequest as typeof fetch,
      now: () => new Date('2026-08-16T10:00:00.000Z'),
    })

    await expect(gateway.agentStatus()).resolves.toMatchObject({
      available: true,
      providerConfigured: true,
      outputEnabled: false,
      modelMapping: { opus: 'custom-sol' },
      runtimeControls: {
        passiveAutoReply: {
          actualEnabled: false,
          state: 'disabled',
          rolloutMode: 'off',
          deliveryEnabled: false,
          killSwitch: true,
        },
        proactiveGroupParticipation: {
          actualEnabled: false,
          state: 'shadow',
          stage: 'probe_shadow',
          deliveryEnabled: false,
        },
      },
      warnings: expect.arrayContaining([
        'CONTROL-PLANE CANDIDATE NO SEND',
        'NO MEMORY WRITE',
        'NO TOOL CALL',
        'NO BANDIT',
      ]),
    })
    await expect(gateway.respond({
      conversationId: 'group-1',
      conversationName: '项目讨论群',
      conversationType: 'group',
      prompt: '完整分析当前架构并给出讨论建议',
      answerProfile: 'long',
      messages: [
        { senderName: '群成员', content: '下午把接口联调一下', mine: false },
        { senderName: '嘟嘟哒', content: '收到', mine: true },
      ],
    })).resolves.toMatchObject({
      candidate: '建议先确认接口契约，再按主链路完成一次联调。',
      tier: 'opus',
      model: 'custom-sol',
      reasoning: 'high',
      answerProfile: 'long',
      replyIntensity: 'active',
      contextLength: 'extended',
      groupChatStyle: 'technical',
      contextUsage: {
        messageLimit: 60,
        characterLimit: 36_000,
        messagesRead: 2,
      },
      generatedAt: '2026-08-16T10:00:00.000Z',
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
      runtimePath: 'candidate_fallback',
    })
    expect(providerRequest).toHaveBeenCalledOnce()
  })

  it('projects the live Dududa rollout config instead of a hard-coded off state', async () => {
    const root = await fixtureRoot()
    const runtimeConfigPath = join(root, 'runtime.json')
    const runtimeStatusPath = join(root, 'runtime-status.json')
    await writeFile(runtimeConfigPath, JSON.stringify({
      runtime_enabled: true,
      rollout_mode: 'canary',
      rollout_delivery_enabled: true,
      rollout_kill_switch: false,
      rollout_allowlisted_groups: ['*'],
    }))
    await writeFile(runtimeStatusPath, JSON.stringify({ ready: true }))
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      runtimeConfigPath,
      runtimeStatusPath,
    })

    await expect(gateway.agentStatus()).resolves.toMatchObject({
      runtimeControls: {
        passiveAutoReply: {
          actualEnabled: true,
          state: 'enabled',
          rolloutMode: 'canary',
          deliveryEnabled: true,
          killSwitch: false,
          summary: expect.stringContaining('所有群'),
        },
      },
      warnings: expect.arrayContaining(['DUDUDA 2.0 PASSIVE RUNTIME ACTIVE']),
    })
    await expect(gateway.agentCatalog()).resolves.toMatchObject({
      plugins: expect.arrayContaining([
        expect.objectContaining({
          id: 'icourse.read',
          runtimeTarget: 'astrbot',
          runtimeReadiness: 'online',
        }),
      ]),
    })
  })

  it('uses the AstrBot 2.0 no-send preview and reports the real iCourse call', async () => {
    const root = await fixtureRoot()
    const scope = {
      accountId: 'qq-3296147894',
      conversationId: 'qq-3296147894:group:364894085',
    }
    const preview = vi.fn(async () => ({
      runId: 'runtime-preview-1',
      candidate: '吴天老师的公开评课结果已由 iCourse 返回并完成总结。',
      tier: 'sonnet' as const,
      model: 'gpt-5.6-terra',
      reasoning: 'low' as const,
      answerProfile: 'long' as const,
      reasonCodes: ['delivery_ready', 'runtime.preview.no_send'],
      latencyMs: 321,
      generatedAt: '2026-08-28T09:00:00.000Z',
      messagesRead: 1,
      charactersRead: 9,
      outputCalls: 0 as const,
      memoryWrites: 0 as const,
      toolCalls: 1,
    }))
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      runtimePreview: { preview },
    })
    const policy = await gateway.agentConfig(scope)
    await gateway.saveAgentConfig({
      scope,
      policy: {
        ...policy,
        plugins: { ...policy.plugins, 'icourse.read': 'on' },
      },
    })

    await expect(gateway.respond({
      ...scope,
      conversationName: '测试群',
      conversationType: 'group',
      prompt: '查询评课社区吴天',
      messages: [],
    })).resolves.toMatchObject({
      runtimePath: 'dududa_2_preview',
      candidate: '吴天老师的公开评课结果已由 iCourse 返回并完成总结。',
      tier: 'sonnet',
      model: 'gpt-5.6-terra',
      answerProfile: 'long',
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 1,
      effectiveSelection: {
        plugins: {
          'icourse.read': {
            selectedForRun: true,
            triggerMatched: true,
          },
        },
      },
    })
    expect(preview).toHaveBeenCalledWith({
      ...scope,
      prompt: '查询评课社区吴天',
    })
  })

  it('does not report an active Runtime before the assembly is ready', async () => {
    const root = await fixtureRoot()
    const runtimeConfigPath = join(root, 'runtime.json')
    const runtimeStatusPath = join(root, 'runtime-status.json')
    await writeFile(runtimeConfigPath, JSON.stringify({
      runtime_enabled: true,
      rollout_mode: 'canary',
      rollout_delivery_enabled: true,
      rollout_kill_switch: false,
      rollout_allowlisted_groups: ['*'],
    }))
    await writeFile(runtimeStatusPath, JSON.stringify({ ready: false }))
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      runtimeConfigPath,
      runtimeStatusPath,
    })

    await expect(gateway.agentStatus()).resolves.toMatchObject({
      runtimeControls: {
        passiveAutoReply: {
          actualEnabled: false,
          state: 'disabled',
          summary: expect.stringContaining('尚未就绪'),
        },
      },
    })
    await expect(gateway.agentCatalog()).resolves.toMatchObject({
      plugins: expect.arrayContaining([
        expect.objectContaining({
          id: 'icourse.read',
          runtimeTarget: 'astrbot',
          runtimeReadiness: 'configured',
        }),
      ]),
    })
  })

  it('persists scoped policy and keeps locked, preferred and adaptive selections distinct', async () => {
    const root = await fixtureRoot()
    const providerRequest = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).toMatchObject({
        model: 'custom-luna',
        reasoning: { effort: 'high' },
        max_output_tokens: 1_200,
      })
      expect(String(body.input)).not.toContain('[msg-10]')
      expect(String(body.input)).toContain('[msg-19]')
      expect(String(body.instructions)).toContain('在多人讨论中保持克制和留白')
      return new Response(JSON.stringify({ output_text: '先把现象和约束列清楚，再逐项排查。' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    const options = {
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      models: { haiku: 'custom-luna' },
      fetchImpl: providerRequest as typeof fetch,
      now: () => new Date('2026-08-17T08:00:00.000Z'),
    }
    const gateway = new FileInternalTestGateway(options)

    const catalog = await gateway.agentCatalog()
    expect(catalog.agent).toMatchObject({
      consoleRole: 'super_admin',
      executionRole: 'admin',
    })
    expect(catalog.models).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'custom-luna', tier: 'haiku', available: true, modalities: ['text'] }),
    ]))
    expect(catalog.plugins).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'icourse.read',
        available: true,
        installed: true,
        policyManaged: true,
        runtimeTarget: 'astrbot',
        runtimeReadiness: 'configured',
        executionKind: 'agent_capability',
        kind: 'mcp',
      }),
      expect.objectContaining({ id: 'ustc.young.read', available: true, kind: 'mcp' }),
      expect.objectContaining({ id: 'ustc.academic.read', available: true, kind: 'mcp' }),
      expect.objectContaining({ id: 'ustc.shuttle.read', available: true, kind: 'mcp' }),
      expect.objectContaining({
        id: 'image.generate.gpt-image-2',
        available: false,
        installed: true,
        policyManaged: true,
        runtimeTarget: 'web_agent',
        runtimeReadiness: 'unavailable',
        executionKind: 'agent_capability',
        kind: 'image_generation',
        model: 'gpt-image-2',
      }),
      expect.objectContaining({
        id: 'social.reread.auto',
        displayName: '自动复读',
        kind: 'social_automation',
        installed: true,
        available: true,
        policyManaged: true,
        requiredRole: 'super_admin',
        executionRole: 'admin',
        runtimeTarget: 'astrbot',
        runtimeReadiness: 'configured',
        executionKind: 'passive_behavior',
      }),
      expect.objectContaining({
        id: 'sub2api.auto_query',
        displayName: '/sub2api 自动查询',
        kind: 'readonly_query',
        installed: true,
        available: true,
        builtIn: true,
        policyManaged: true,
        requiredRole: 'super_admin',
        executionRole: 'admin',
        runtimeTarget: 'astrbot',
        runtimeReadiness: 'configured',
        executionKind: 'command_auto_reply',
      }),
    ]))
    expect(catalog.replyIntensities).toEqual(['quiet', 'normal', 'active'])
    expect(catalog.contextLengths).toEqual([
      { id: 'compact', messageLimit: 12, characterLimit: 6_000 },
      { id: 'standard', messageLimit: 30, characterLimit: 18_000 },
      { id: 'extended', messageLimit: 60, characterLimit: 36_000 },
    ])
    expect(catalog.groupChatStyles).toEqual(['restrained', 'natural', 'lively', 'technical'])
    expect(catalog.replyIntensityNotice).toContain('Rollout')
    expect(catalog.policyDefaults).toMatchObject({
      replyIntensity: { mode: 'adaptive', preferred: 'normal' },
      contextLength: { mode: 'adaptive', preferred: 'standard' },
      groupChatStyle: { mode: 'adaptive', preferred: 'natural' },
      plugins: {
        'social.reread.auto': 'off',
        'sub2api.auto_query': 'off',
      },
    })

    await expect(gateway.saveAgentConfig({
      scope: { accountId: 'bot-1', conversationId: 'group-42' },
      policy: {
        plugins: {
          'social.reread.auto': 'auto',
          'sub2api.auto_query': 'on',
        },
      },
    })).resolves.toMatchObject({
      plugins: {
        'social.reread.auto': 'auto',
        'sub2api.auto_query': 'on',
      },
    })

    await gateway.saveAgentConfig({
      scope: { accountId: 'bot-1', conversationId: 'group-42' },
      policy: {
        enabled: true,
        modelTier: { mode: 'locked', preferred: 'haiku', allowed: ['haiku', 'opus'] },
        reasoning: { mode: 'preferred', preferred: 'medium', allowed: ['low', 'medium', 'high'] },
        answerProfile: { mode: 'adaptive', preferred: 'medium', allowed: ['short', 'medium', 'long'] },
        replyIntensity: { mode: 'preferred', preferred: 'normal', allowed: ['quiet', 'normal', 'active'] },
        contextLength: { mode: 'locked', preferred: 'compact', allowed: ['compact', 'standard'] },
        groupChatStyle: { mode: 'locked', preferred: 'restrained', allowed: ['restrained', 'natural'] },
        plugins: {
          'icourse.read': 'off',
          'image.generate.gpt-image-2': 'off',
          'social.reread.auto': 'auto',
          'sub2api.auto_query': 'on',
        },
      },
    })

    const reloaded = new FileInternalTestGateway(options)
    await expect(reloaded.agentConfig({ accountId: 'bot-1', conversationId: 'group-42' })).resolves.toMatchObject({
      scope: { accountId: 'bot-1', conversationId: 'group-42' },
      modelTier: { mode: 'locked', preferred: 'haiku' },
      reasoning: { mode: 'preferred', preferred: 'medium' },
      replyIntensity: { mode: 'preferred', preferred: 'normal' },
      contextLength: { mode: 'locked', preferred: 'compact' },
      groupChatStyle: { mode: 'locked', preferred: 'restrained' },
      plugins: {
        'icourse.read': 'off',
        'social.reread.auto': 'auto',
        'sub2api.auto_query': 'on',
      },
      updatedAt: '2026-08-17T08:00:00.000Z',
    })

    await expect(reloaded.respond({
      accountId: 'bot-1',
      conversationId: 'group-42',
      conversationName: '开发群',
      conversationType: 'group',
      prompt: '请完整分析这个架构问题并给出迁移方案',
      answerProfile: 'long',
      messages: Array.from({ length: 20 }, (_, index) => ({
        senderName: `成员-${index}`,
        content: `[msg-${String(index).padStart(2, '0')}]${'甲'.repeat(690)}`,
      })),
    })).resolves.toMatchObject({
      tier: 'haiku',
      model: 'custom-luna',
      reasoning: 'high',
      answerProfile: 'long',
      replyIntensity: 'active',
      contextLength: 'compact',
      groupChatStyle: 'restrained',
      contextUsage: {
        messageLimit: 12,
        characterLimit: 6_000,
        messagesRead: 9,
        charactersRead: 6_000,
      },
      effectiveSelection: {
        scope: { accountId: 'bot-1', conversationId: 'group-42' },
        policySource: 'saved',
        modelTier: 'haiku',
        reasoning: 'high',
        answerProfile: 'long',
        replyIntensity: 'active',
        contextLength: 'compact',
        groupChatStyle: 'restrained',
        contextUsage: {
          messageLimit: 12,
          characterLimit: 6_000,
          messagesRead: 9,
          charactersRead: 6_000,
        },
        plugins: {
          'icourse.read': { mode: 'off', available: true, eligible: false, selectedForRun: false },
          'social.reread.auto': {
            mode: 'auto',
            available: true,
            eligible: true,
            selectedForRun: false,
            applicable: false,
            triggerMatched: false,
            runtimeTarget: 'astrbot',
            runtimeReadiness: 'configured',
            selectionReason: 'not_applicable',
          },
          'sub2api.auto_query': {
            mode: 'on',
            available: true,
            eligible: true,
            selectedForRun: false,
            applicable: false,
            triggerMatched: false,
            runtimeTarget: 'astrbot',
            runtimeReadiness: 'configured',
            selectionReason: 'not_applicable',
          },
        },
      },
      reasonCodes: expect.arrayContaining([
        'model.locked_by_admin',
        'reasoning.preferred_overridden',
        'answer_profile.adaptive',
        'reply_intensity.preferred_overridden',
        'context_length.locked_by_admin',
        'group_chat_style.locked_by_admin',
        'plugin.icourse.read.off_by_admin',
        'plugin.social.reread.auto.waiting_for_group_repeat',
        'plugin.sub2api.auto_query.waiting_for_exact_command',
        'tools.none_called_by_candidate_runtime',
      ]),
    })
    expect(providerRequest).toHaveBeenCalledOnce()
  })

  it('reports deterministic plugin triggers without claiming the Web candidate runtime executed them', async () => {
    const root = await fixtureRoot()
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      fetchImpl: vi.fn(async () => new Response(JSON.stringify({ output_text: '候选预览' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch,
    })
    await gateway.saveAgentConfig({
      scope: { accountId: 'bot-1', conversationId: 'group-plugins' },
      policy: {
        plugins: {
          'social.reread.auto': 'auto',
          'sub2api.auto_query': 'on',
        },
      },
    })

    await expect(gateway.respond({
      accountId: 'bot-1',
      conversationId: 'group-plugins',
      conversationName: '插件测试群',
      conversationType: 'group',
      prompt: '/sub2api status',
      messages: [
        { senderName: '成员甲', content: '确实如此' },
        { senderName: '成员乙', content: '确实如此' },
      ],
    })).resolves.toMatchObject({
      effectiveSelection: {
        plugins: {
          'social.reread.auto': {
            eligible: true,
            selectedForRun: false,
            applicable: true,
            triggerMatched: true,
            runtimeTarget: 'astrbot',
            runtimeReadiness: 'configured',
            selectionReason: 'trigger_matched',
          },
          'sub2api.auto_query': {
            eligible: true,
            selectedForRun: false,
            applicable: true,
            triggerMatched: true,
            runtimeTarget: 'astrbot',
            runtimeReadiness: 'configured',
            selectionReason: 'trigger_matched',
          },
        },
      },
      reasonCodes: expect.arrayContaining([
        'plugin.social.reread.auto.group_repeat_trigger_matched_not_executed',
        'plugin.sub2api.auto_query.exact_command_trigger_matched_not_executed',
        'tools.none_called_by_candidate_runtime',
      ]),
      toolCalls: 0,
    })
  })

  it('loads the de-identified projection, generates a no-send candidate and records human feedback', async () => {
    const root = await fixtureRoot()
    const providerRequest = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(String(init?.headers && (init.headers as Record<string, string>).Authorization)).toContain('test-key')
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).toMatchObject({ model: 'custom-terra', reasoning: { effort: 'medium' }, store: false })
      expect(String(body.input)).toContain('identity-2：下午一起讨论项目。')
      return new Response(JSON.stringify({
        output: [{ content: [{ type: 'output_text', text: '好呀，下午一起把项目思路捋一遍。' }] }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const feedbackPath = join(root, 'internal-test/feedback.jsonl')
    const gateway = new FileInternalTestGateway({
      dataRoot: root,
      feedbackPath,
      providerBaseUrl: 'https://provider.invalid',
      providerApiKey: 'test-key',
      models: { sonnet: 'custom-terra' },
      fetchImpl: providerRequest as typeof fetch,
      now: () => new Date('2026-08-16T09:00:00.000Z'),
    })

    await expect(gateway.status()).resolves.toMatchObject({
      available: true,
      providerConfigured: true,
      outputEnabled: false,
      sampleCount: 2,
      modelMapping: {
        haiku: 'gpt-5.6-luna',
        sonnet: 'custom-terra',
        opus: 'gpt-5.6-sol',
      },
    })
    await expect(gateway.samples({ bucket: 'short_chat', tools: 'false' })).resolves.toMatchObject({
      total: 1,
      items: [{ window_id: 'window-1' }],
    })

    const candidate = await gateway.generate({ windowId: 'window-1' })
    expect(candidate).toMatchObject({
      windowId: 'window-1',
      candidate: '好呀，下午一起把项目思路捋一遍。',
      tier: 'sonnet',
      model: 'custom-terra',
      answerProfile: 'medium',
      providerCalls: 1,
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    })

    const result = await gateway.feedback({
      windowId: 'window-1',
      runId: candidate.runId,
      verdict: 'accepted',
      note: '长度和语气合适',
      evaluation: {
        shouldReply: 'yes',
        routingReasonable: 4,
        correctness: 5,
        naturalness: 4,
        groupFit: 4,
        lengthFit: 5,
      },
      corrected: {
        semanticComplexity: 'low',
        answerProfile: 'short',
        candidate: 'must-not-be-persisted',
        base_url: 'must-not-be-persisted',
      },
    })
    expect(result.progress).toEqual({
      total: 2,
      evaluated: 1,
      pending: 1,
      accepted: 1,
      rejected: 0,
      needsReview: 0,
    })
    const persisted = JSON.parse((await readFile(feedbackPath, 'utf8')).trim()) as Record<string, unknown>
    expect(persisted).toMatchObject({
      window_id: 'window-1',
      run_id: candidate.runId,
      verdict: 'accepted',
      evidence_mode: 'private_silver_shadow',
      evaluation: {
        should_reply: 'yes',
        routing_reasonable: 4,
        correctness: 5,
        naturalness: 4,
        group_fit: 4,
        length_fit: 5,
      },
      corrected: { semanticComplexity: 'low', answerProfile: 'short' },
    })
    expect(persisted).not.toHaveProperty('candidate')
    expect(persisted.corrected).not.toHaveProperty('candidate')
    expect(persisted.corrected).not.toHaveProperty('base_url')
  })

  it('keeps missing or relative private data configuration unavailable', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dududa-internal-test-missing-'))
    temporaryDirectories.push(root)
    await expect(createInternalTestGateway({}).status()).resolves.toMatchObject({
      available: false,
      sampleCount: 0,
    })
    await expect(createInternalTestGateway({
      DUDUDA_INTERNAL_TEST_DATA_ROOT: join(root, 'missing'),
    }).status()).resolves.toMatchObject({
      available: false,
      sampleCount: 0,
      warnings: expect.arrayContaining(['内测语料 Demo 尚未生成']),
    })
    await expect(createInternalTestGateway({
      DUDUDA_INTERNAL_TEST_DATA_ROOT: 'relative/private-data',
      DUDUDA_INTERNAL_TEST_HAIKU_MODEL: 'custom-luna',
    }).status()).resolves.toMatchObject({
      available: false,
      modelMapping: { haiku: 'custom-luna' },
    })
  })
})
