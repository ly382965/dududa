import { describe, expect, it } from 'vitest'

import { mapMessage, normalizeSegments, type OneBotMessage, type OneBotSegment } from './mapper'

describe('OneBot rich message mapping', () => {
  it('preserves ordered known segments and safely summarizes unknown data', () => {
    const segments: OneBotSegment[] = [
      { type: 'reply', data: { id: '91', seq: '190', qq: '234567890', name: '成员', text: '原消息' } },
      { type: 'text', data: { text: '你好 ' } },
      { type: 'at', data: { qq: '345678901', name: '小明' } },
      { type: 'face', data: { id: '14', summary: '[微笑]' } },
      {
        type: 'image',
        data: {
          resource_id: 'resource-image',
          url: 'https://gchat.qpic.cn/image',
          file: '/tmp/never-expose.png',
          summary: '[图片]',
          width: 640,
          height: 480,
        },
      },
      { type: 'record', data: { resource_id: 'voice-1', url: 'https://gchat.qpic.cn/voice', duration: 3 } },
      { type: 'video', data: { resource_id: 'video-1', url: 'https://gchat.qpic.cn/video', duration: 4 } },
      { type: 'file', data: { file_id: 'file-1', name: '报告.pdf', size: 1024, path: '/private/report.pdf' } },
      { type: 'forward', data: { id: 'forward-1', count: 2 } },
      { type: 'markdown', data: { content: '**真实内容**' } },
      {
        type: 'json',
        data: {
          data: JSON.stringify({
            app: 'com.tencent.miniapp',
            prompt: '[应用]',
            meta: { detail_1: { title: '卡片标题', jumpUrl: 'javascript:alert(1)' } },
          }),
        },
      },
      { type: 'future-secret-segment', data: { token: 'must-not-leak', path: '/root/private' } },
    ]

    const normalized = normalizeSegments(segments, (url) => `/api/media/${encodeURIComponent(url)}`)

    expect(normalized.map((segment) => segment.type)).toEqual([
      'reply',
      'text',
      'mention',
      'face',
      'image',
      'audio',
      'video',
      'file',
      'forward',
      'markdown',
      'light_app',
      'unknown',
    ])
    expect(normalized[4]).toMatchObject({
      type: 'image',
      resourceId: 'resource-image',
      url: '/api/media/https%3A%2F%2Fgchat.qpic.cn%2Fimage',
      width: 640,
      height: 480,
    })
    expect(normalized[10]).toMatchObject({
      type: 'light_app',
      app: 'com.tencent.miniapp',
      title: '卡片标题',
      url: undefined,
    })
    expect(normalized[11]).toEqual({
      type: 'unknown',
      segmentType: 'future-secret-segment',
      summary: '[不支持的消息: future-secret-segment]',
    })
    expect(JSON.stringify(normalized)).not.toContain('must-not-leak')
    expect(JSON.stringify(normalized)).not.toContain('/root/private')
    expect(JSON.stringify(normalized)).not.toContain('/tmp/never-expose.png')
  })

  it('binds a normalized message to its account and conversation', () => {
    const raw: OneBotMessage = {
      self_id: 123456789,
      time: 1_785_742_400,
      message_id: 101,
      message_seq: 201,
      user_id: 234567890,
      group_id: 345678901,
      message_type: 'group',
      sender: { user_id: 234567890, nickname: '成员' },
      message: [{ type: 'text', data: { text: '真实消息' } }],
    }

    expect(mapMessage('qq-123456789', '123456789', raw, () => undefined)).toMatchObject({
      id: 'qq-123456789:group:345678901:101',
      accountId: 'qq-123456789',
      conversationId: 'qq-123456789:group:345678901',
      messageId: '101',
      messageSeq: '201',
      content: '真实消息',
      segments: [{ type: 'text', text: '真实消息' }],
    })
    expect(mapMessage('qq-987654321', '987654321', raw, () => undefined)).toBeUndefined()
  })
})
