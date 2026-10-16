import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { workspaceAdapter } from '../../services/workspace-adapter'
import { groupUploadFingerprint, uncertainGroupUploadBlocked } from '../../services/upload-guard'
import type { Account, EssencePage, GroupFilePage, GroupPermissions } from '../../types/workspace'
import GroupResourcesPanel from './GroupResourcesPanel.vue'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

const account: Account = {
  id: 'qq-123456789',
  botId: '123456789',
  name: '真实账号',
  shortName: '真实账号',
  avatar: '',
  status: 'online',
  unread: 0,
  role: 'bot',
  accent: 'cyan',
}

const permissions: GroupPermissions = Object.fromEntries(
  [
    'mentionAll', 'setAdmin', 'kickMembers', 'editOwnCard', 'rename', 'muteAll', 'quit',
    'readEssence', 'readAnnouncements', 'deleteAnnouncements', 'readFiles', 'uploadFiles',
    'manageFiles', 'packetFiles', 'renameFolders',
  ].map((name) => [name, { allowed: false }]),
) as unknown as GroupPermissions

function essence(groupId: string, content: string): EssencePage {
  return {
    items: [{
      id: `${groupId}:essence`,
      accountId: account.id,
      groupId,
      messageId: '101',
      senderId: '234567890',
      senderName: '真实成员',
      operatorId: account.botId,
      operatorName: account.name,
      operatorTime: 1_785_742_400,
      content,
      segments: [{ type: 'text', text: content }],
    }],
    offset: 0,
    hasMore: false,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('GroupResourcesPanel', () => {
  it('ignores a stale essence response after switching groups', async () => {
    const first = deferred<EssencePage>()
    const second = deferred<EssencePage>()
    vi.spyOn(workspaceAdapter, 'loadEssence')
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    const wrapper = mount(GroupResourcesPanel, {
      props: { account, groupId: '345678901', permissions },
      global: { plugins: [createPinia()] },
    })
    await Promise.resolve()
    await wrapper.setProps({ groupId: '456789012' })
    second.resolve(essence('456789012', '第二个群的精华'))
    await flushPromises()
    first.resolve(essence('345678901', '迟到的第一个群精华'))
    await flushPromises()

    expect(wrapper.text()).toContain('第二个群的精华')
    expect(wrapper.text()).not.toContain('迟到的第一个群精华')
  })

  it('persists the upload guard before a group-file request finishes and clears it on success', async () => {
    const groupId = '345678901'
    const allowed = {
      ...permissions,
      readFiles: { allowed: true },
      uploadFiles: { allowed: true },
      packetFiles: { allowed: true },
    }
    const page: GroupFilePage = {
      accountId: account.id,
      groupId,
      parentId: '/',
      files: [],
      folders: [],
      truncated: false,
      permissions: allowed,
    }
    const pending = deferred<{ kind: 'file'; name: string; size: number }>()
    vi.spyOn(workspaceAdapter, 'loadEssence').mockResolvedValue(essence(groupId, '精华'))
    vi.spyOn(workspaceAdapter, 'loadGroupFiles').mockResolvedValue(page)
    const upload = vi.spyOn(workspaceAdapter, 'uploadGroupFile').mockImplementation(async () => pending.promise)
    const wrapper = mount(GroupResourcesPanel, {
      props: { account, groupId, permissions: allowed },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.findAll('.resource-tabs button').find((button) => button.text().includes('文件'))!.trigger('click')
    await flushPromises()
    const file = new File(['panel bytes'], '面板文件.txt', { type: 'text/plain' })
    const fingerprint = await groupUploadFingerprint(account.id, groupId, '/', file)
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await vi.waitFor(() => expect(upload).toHaveBeenCalledOnce())

    expect(uncertainGroupUploadBlocked(fingerprint)).toBe(true)
    pending.resolve({ kind: 'file', name: file.name, size: file.size })
    await vi.waitFor(() => expect(uncertainGroupUploadBlocked(fingerprint)).toBe(false))
  })
})
