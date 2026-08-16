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
        store: false,
      })
      expect(String(body.input)).toContain('群成员：下午把接口联调一下')
      expect(String(body.input)).toContain('操作员指令：\n给出一个完整的讨论建议')
      expect(String(body.instructions)).toContain('不要调用工具')
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
      warnings: expect.arrayContaining(['NO SEND', 'NO MEMORY WRITE', 'NO TOOL CALL', 'NO BANDIT']),
    })
    await expect(gateway.respond({
      conversationId: 'group-1',
      conversationName: '项目讨论群',
      prompt: '给出一个完整的讨论建议',
      answerProfile: 'long',
      messages: [
        { senderName: '群成员', content: '下午把接口联调一下', mine: false },
        { senderName: '嘟嘟哒', content: '收到', mine: true },
      ],
    })).resolves.toMatchObject({
      candidate: '建议先确认接口契约，再按主链路完成一次联调。',
      tier: 'opus',
      model: 'custom-sol',
      answerProfile: 'long',
      generatedAt: '2026-08-16T10:00:00.000Z',
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    })
    expect(providerRequest).toHaveBeenCalledOnce()
  })

  it('loads the de-identified projection, generates a no-send candidate and records human feedback', async () => {
    const root = await fixtureRoot()
    const providerRequest = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      expect(String(init?.headers && (init.headers as Record<string, string>).Authorization)).toContain('test-key')
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).toMatchObject({ model: 'custom-terra', store: false })
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
