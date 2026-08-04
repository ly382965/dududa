import { afterEach, describe, expect, it } from 'vitest'

import {
  clearUncertainGroupUpload,
  groupUploadFingerprint,
  markUncertainGroupUpload,
  uncertainGroupUploadBlocked,
} from './upload-guard'

afterEach(() => window.localStorage.clear())

describe('group upload uncertainty guard', () => {
  it('binds a persistent guard to account, group, folder, metadata, and file content', async () => {
    const file = new File(['real file bytes'], '真实文件.txt', { type: 'text/plain' })
    const fingerprint = await groupUploadFingerprint('qq-111111111', '345678901', '/', file)
    const anotherAccount = await groupUploadFingerprint('qq-222222222', '345678901', '/', file)
    const anotherContent = await groupUploadFingerprint(
      'qq-111111111',
      '345678901',
      '/',
      new File(['different bytes'], '真实文件.txt', { type: 'text/plain' }),
    )

    expect(markUncertainGroupUpload(fingerprint, 1_000)).toBe(true)
    expect(uncertainGroupUploadBlocked(fingerprint, 1_001)).toBe(true)
    expect(uncertainGroupUploadBlocked(anotherAccount, 1_001)).toBe(false)
    expect(uncertainGroupUploadBlocked(anotherContent, 1_001)).toBe(false)
    clearUncertainGroupUpload(fingerprint, 1_002)
    expect(uncertainGroupUploadBlocked(fingerprint, 1_003)).toBe(false)
    expect(markUncertainGroupUpload(fingerprint, 1_004)).toBe(true)
    expect(uncertainGroupUploadBlocked(fingerprint, 601_005)).toBe(false)
  })

  it('refuses to claim persistence when browser storage cannot be written', () => {
    const brokenStorage = {
      getItem: () => null,
      setItem: () => { throw new DOMException('quota exceeded', 'QuotaExceededError') },
    } as unknown as Storage
    expect(markUncertainGroupUpload('fingerprint', 1_000, brokenStorage)).toBe(false)
  })
})
