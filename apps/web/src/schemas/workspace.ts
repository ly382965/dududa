import { z } from 'zod'

const numericId = z.string().regex(/^\d{1,24}$/)

const textSegmentSchema = z
  .object({
    type: z.literal('text'),
    text: z.string().min(1).max(4000),
  })
  .strict()

const mentionSegmentSchema = z
  .object({
    type: z.literal('mention'),
    userId: numericId.optional(),
    label: z.string().max(128).default(''),
    all: z.boolean().default(false),
  })
  .strict()
  .refine((value) => value.all || Boolean(value.userId), {
    message: '普通提及必须包含 QQ 号',
    path: ['userId'],
  })

const replySegmentSchema = z
  .object({
    type: z.literal('reply'),
    messageId: numericId.optional(),
    messageSeq: numericId.optional(),
  })
  .strict()
  .refine((value) => Boolean(value.messageId || value.messageSeq), {
    message: '回复必须包含消息标识',
    path: ['messageId'],
  })

const faceSegmentSchema = z
  .object({
    type: z.literal('face'),
    faceId: numericId,
    name: z.string().max(128).optional(),
    market: z.literal(false).default(false),
  })
  .strict()

export const outgoingMessageSegmentSchema = z.discriminatedUnion('type', [
  textSegmentSchema,
  mentionSegmentSchema,
  replySegmentSchema,
  faceSegmentSchema,
])

export const sendMessageRequestSchema = z
  .union([
    z.object({ content: z.string().trim().min(1).max(4000) }).strict(),
    z
      .object({
        segments: z.array(outgoingMessageSegmentSchema).min(1).max(100),
      })
      .strict(),
  ])
  .transform((value) =>
    'content' in value ? [{ type: 'text' as const, text: value.content }] : value.segments,
  )

export const historyQuerySchema = z
  .object({
    limit: z.coerce.number().int().min(1).max(100).default(50),
    before: z.string().min(1).max(2048).optional(),
    after: z.string().min(1).max(2048).optional(),
  })
  .strict()
  .refine((value) => !(value.before && value.after), {
    message: 'before 与 after 不能同时使用',
  })
