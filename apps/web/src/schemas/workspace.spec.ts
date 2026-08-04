import { describe, expect, it } from 'vitest'

import { historyQuerySchema, sendMessageRequestSchema } from './workspace'

describe('workspace schemas', () => {
  it('keeps the legacy text request as one normalized segment', () => {
    expect(sendMessageRequestSchema.parse({ content: '  真实消息  ' })).toEqual([
      { type: 'text', text: '真实消息' },
    ])
  })

  it('rejects raw paths and arbitrary OneBot segment types', () => {
    expect(() =>
      sendMessageRequestSchema.parse({ segments: [{ type: 'image', file: '/tmp/private.png' }] }),
    ).toThrow()
    expect(() => sendMessageRequestSchema.parse({ segments: [{ type: 'raw', data: {} }] })).toThrow()
    expect(
      sendMessageRequestSchema.parse({ segments: [{ type: 'custom_face', handle: 'a'.repeat(32) }] }),
    ).toEqual([{ type: 'custom_face', handle: 'a'.repeat(32) }])
    expect(() =>
      sendMessageRequestSchema.parse({
        segments: [{ type: 'custom_face', handle: 'a'.repeat(32), url: 'https://gchat.qpic.cn/arbitrary' }],
      }),
    ).toThrow()
  })

  it('requires account-safe opaque history query shapes', () => {
    expect(historyQuerySchema.parse({ limit: '25', before: 'cursor' })).toEqual({
      limit: 25,
      before: 'cursor',
    })
    expect(() => historyQuerySchema.parse({ before: 'a', after: 'b' })).toThrow()
    expect(() => historyQuerySchema.parse({ limit: 101 })).toThrow()
  })
})
