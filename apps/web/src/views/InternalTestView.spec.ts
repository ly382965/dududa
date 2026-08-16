import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { InternalTestAdapter } from '../services/internal-test'
import type { InternalTestCandidate, InternalTestSample, InternalTestStatus } from '../types/internal-test'
import InternalTestView from './InternalTestView.vue'

const sample: InternalTestSample = {
  window_id: 'window-private-1',
  primary_bucket: 'short_chat',
  message_count: 2,
  speaker_count: 2,
  messages: [
    { message_ref: 'm1', sender_ref: 'speaker-a', text: '下午还开会吗？' },
    { message_ref: 'm2', sender_ref: 'speaker-b', text: '三点在活动室。' },
  ],
  silver: { need_tools: false, semantic_complexity: 'medium', answer_profile: 'short' },
  student: {
    need_tools: { label: false, confidence: .91 },
    semantic_complexity: { label: 'low', confidence: .82 },
    answer_profile: { label: 'short', confidence: .88 },
  },
  tier_preview: { selected_tier: 'haiku', production_route: false },
}

describe('InternalTestView', () => {
  it('renders the private no-send projection and submits repository-external feedback', async () => {
    const candidate: InternalTestCandidate = {
      runId: 'run-1',
      windowId: sample.window_id,
      candidate: '开，三点活动室见～',
      tier: 'haiku',
      model: 'gpt-5.6-luna',
      answerProfile: 'short',
      latencyMs: 420,
      generatedAt: '2026-08-16T10:00:00Z',
      evidenceMode: 'private_silver_shadow',
      providerCalls: 1,
      outputCalls: 0,
      memoryWrites: 0,
      toolCalls: 0,
    }
    const generate = vi.fn(async () => candidate)
    const feedback = vi.fn(async () => ({
      ok: true as const,
      feedbackId: 'feedback-1',
      progress: { total: 1, evaluated: 1, pending: 0, accepted: 1, rejected: 0, needsReview: 0 },
    }))
    const adapter: InternalTestAdapter = {
      status: vi.fn(async () => ({
        available: true,
        evidenceMode: 'private_silver_shadow',
        outputEnabled: false,
        providerConfigured: true,
        sampleCount: 1,
        modelMapping: {
          haiku: 'gpt-5.6-luna',
          sonnet: 'gpt-5.6-terra',
          opus: 'gpt-5.6-sol',
        },
        warnings: ['PRIVATE DEVELOPMENT DATA', 'NO SEND'],
      } satisfies InternalTestStatus)),
      samples: vi.fn(async () => ({ items: [sample], total: 1, offset: 0, limit: 40 })),
      progress: vi.fn(async () => ({ total: 1, evaluated: 0, pending: 1, accepted: 0, rejected: 0, needsReview: 0 })),
      generate,
      feedback,
    }

    const wrapper = mount(InternalTestView, { props: { adapter } })
    await flushPromises()

    expect(wrapper.text()).toContain('PRIVATE DEVELOPMENT DATA')
    expect(wrapper.text()).toContain('SILVER NOT GOLD')
    expect(wrapper.text()).toContain('三点在活动室。')
    expect(wrapper.text()).toContain('GPT-5.6 Luna')
    expect(wrapper.text()).toContain('后端返回最终模型')

    await wrapper.get('[data-testid="generate-candidate"]').trigger('click')
    await flushPromises()
    expect(generate).toHaveBeenCalledWith(sample.window_id)
    expect(wrapper.get('[data-testid="candidate-answer"]').text()).toContain('开，三点活动室见～')
    expect(wrapper.get('[data-testid="candidate-answer"]').text()).toContain('Output 0')

    await wrapper.get('[data-testid="submit-feedback"]').trigger('submit')
    await flushPromises()
    expect(feedback).toHaveBeenCalledWith(expect.objectContaining({
      windowId: sample.window_id,
      runId: 'run-1',
      verdict: 'accepted',
      evaluation: expect.objectContaining({ routingReasonable: 4, lengthFit: 4 }),
    }))
    expect(wrapper.text()).toContain('人工评价已追加到仓库外 JSONL')
  })
})
