import { z } from 'zod'

const positiveRevision = z.number().int().positive()

export const previewGroupServiceSchema = z.object({
  profileId: z.string().trim().min(1).max(128),
  profileRevision: positiveRevision,
  expectedOnboardingRevision: positiveRevision,
  expectedAssignmentRevision: positiveRevision.optional(),
}).strict()

export const groupServiceCommandSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.enum(['activate', 'update']),
    expectedOnboardingRevision: positiveRevision,
    expectedAssignmentRevision: positiveRevision.optional(),
    previewId: z.string().trim().min(1).max(256),
    previewDigest: z.string().trim().min(1).max(512),
  }).strict(),
  z.object({
    action: z.literal('pause'),
    expectedOnboardingRevision: positiveRevision,
    expectedAssignmentRevision: positiveRevision,
  }).strict(),
  z.object({
    action: z.literal('resume'),
    expectedOnboardingRevision: positiveRevision,
    expectedAssignmentRevision: positiveRevision,
  }).strict(),
  z.object({
    action: z.literal('rollback'),
    expectedOnboardingRevision: positiveRevision,
    expectedAssignmentRevision: positiveRevision,
    rollbackRevision: positiveRevision,
  }).strict(),
])
