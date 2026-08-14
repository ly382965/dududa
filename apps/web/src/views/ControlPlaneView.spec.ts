import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { ControlPlaneAdapter } from '../services/control-plane'
import type {
  ControlPlaneReceipt,
  GroupServiceAssignment,
  GroupServiceCommandRequest,
  GroupServicePreview,
  PendingInbox,
  ProfileCatalog,
} from '../types/control-plane'
import type { Account } from '../types/workspace'
import ControlPlaneView from './ControlPlaneView.vue'

const account = {
  id: 'qq-123456789',
  botId: '123456789',
  name: '嘟嘟哒',
  shortName: '嘟嘟哒',
  avatar: '',
  status: 'online',
  unread: 0,
  role: 'bot',
  accent: 'cyan',
} as Account

const scope = { platform: 'qq', botId: account.botId, groupId: '345678901' }

function receipt(action: string, reason: string): ControlPlaneReceipt {
  return {
    receiptId: `receipt-${action}`,
    commandId: `command-${action}`,
    action: `group_service.${action}`,
    outcome: 'succeeded',
    reasonCodes: [reason],
    committedAt: '2026-08-14T13:00:00Z',
  }
}

function preview(
  id: string,
  onboardingRevision: number,
  assignmentRevision?: number,
): GroupServicePreview {
  return {
    previewId: id,
    scope,
    profileId: assignmentRevision ? 'profile-expanded' : 'profile-basic',
    profileRevision: 1,
    previewDigest: `digest-${id}`,
    onboardingRevision,
    ...(assignmentRevision ? { assignmentRevision } : {}),
    catalogRevision: 'catalog-v1',
    desiredServiceIds: ['chat', 'memory'],
    effectiveServiceIds: ['chat'],
    resolutions: [
      { serviceId: 'chat', eligible: true, reasonCodes: [] },
      { serviceId: 'memory', eligible: false, reasonCodes: ['service_not_granted'] },
    ],
    expiresAt: '2026-08-14T13:10:00Z',
  }
}

function assignment(
  status: GroupServiceAssignment['status'],
  assignmentRevision: number,
): GroupServiceAssignment {
  return {
    scope,
    assignmentRevision,
    status,
    profileId: assignmentRevision === 1 ? 'profile-basic' : 'profile-expanded',
    profileRevision: 1,
    desiredServiceIds: ['chat', 'memory'],
    effectiveServiceIds: status === 'paused' ? [] : ['chat'],
    previousRevision: assignmentRevision > 1 ? assignmentRevision - 1 : undefined,
    lastKnownGoodRevision: 1,
    activatedAt: '2026-08-14T13:00:00Z',
  }
}

describe('ControlPlaneView', () => {
  it('renders authoritative diffs and drives the complete lifecycle through the adapter', async () => {
    let revision = 0
    let activated = false
    let currentAssignment: GroupServiceAssignment | undefined
    const previewCall = vi.fn(async (_accountId: string, _groupId: string, request: { expectedAssignmentRevision?: number }) => {
      const value = request.expectedAssignmentRevision ? preview('preview-update', 2, 1) : preview('preview-activate', 1)
      return {
        preview: value,
        onboardingRevision: value.onboardingRevision + 1,
        receipt: receipt('preview', 'preview_ready'),
      }
    })
    const command = vi.fn(async (_accountId: string, _groupId: string, request: GroupServiceCommandRequest) => {
      const status = request.action === 'pause'
        ? 'paused'
        : request.action === 'rollback'
          ? 'rolled_back'
          : 'active'
      revision += 1
      currentAssignment = assignment(status, revision)
      activated = true
      return {
        assignment: currentAssignment,
        receipt: receipt(request.action, `${request.action}_committed`),
      }
    })
    const adapter: ControlPlaneAdapter = {
      status: vi.fn(async () => ({ available: true })),
      pendingInbox: vi.fn(async (): Promise<PendingInbox> => ({
        platform: 'qq',
        botId: account.botId,
        items: activated ? [] : [{
          scope,
          status: 'pending_profile',
          revision: 1,
          firstSeenAt: '2026-08-14T12:00:00Z',
          updatedAt: '2026-08-14T12:00:00Z',
        }],
        generatedAt: '2026-08-14T13:00:00Z',
      })),
      managedGroups: vi.fn(async () => ({
        platform: 'qq',
        botId: account.botId,
        items: activated && currentAssignment ? [{
          onboarding: {
            scope,
            status: 'preview_ready' as const,
            revision: 3,
            firstSeenAt: '2026-08-14T12:00:00Z',
            updatedAt: '2026-08-14T13:00:00Z',
            previewId: 'preview-update',
          },
          assignment: currentAssignment,
        }] : [],
        generatedAt: '2026-08-14T13:00:00Z',
      })),
      profileCatalog: vi.fn(async (): Promise<ProfileCatalog> => ({
        revision: 'catalog-v1',
        profiles: [
          {
            profileId: 'profile-basic',
            revision: 1,
            displayName: '基础服务',
            requestedServiceIds: ['chat', 'memory'],
            personaRef: 'dududa-default',
            triggerPolicyRef: 'trigger-default',
            responsePolicyRef: 'response-default',
            modelBudgetPolicyRef: 'budget-default',
            memoryMode: 'read',
            proactiveDefaultEnabled: false,
            strictServices: false,
          },
          {
            profileId: 'profile-expanded',
            revision: 1,
            displayName: '扩展服务',
            requestedServiceIds: ['chat', 'memory'],
            personaRef: 'dududa-default',
            triggerPolicyRef: 'trigger-default',
            responsePolicyRef: 'response-default',
            modelBudgetPolicyRef: 'budget-expanded',
            memoryMode: 'manual_write',
            proactiveDefaultEnabled: false,
            strictServices: false,
          },
        ],
        generatedAt: '2026-08-14T13:00:00Z',
      })),
      preview: previewCall,
      command,
    }
    const wrapper = mount(ControlPlaneView, { props: { account, adapter } })
    await flushPromises()

    await wrapper.get('.preview-button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.service-table').text()).toContain('memory')
    expect(wrapper.get('.service-table').text()).toContain('未授权')
    expect(wrapper.get('.commit-strip').text()).toContain('1 / 2 项服务可生效')

    await wrapper.get('.commit-strip button').trigger('click')
    await flushPromises()
    expect(command).toHaveBeenLastCalledWith(account.id, scope.groupId, {
      action: 'activate',
      expectedOnboardingRevision: 2,
      previewId: 'preview-activate',
      previewDigest: 'digest-preview-activate',
    })
    expect(wrapper.get('.assignment-section').text()).toContain('revision 1')

    await wrapper.get('select[aria-label="群服务档案"]').setValue('profile-expanded')
    await wrapper.get('.preview-button').trigger('click')
    await flushPromises()
    await wrapper.get('.commit-strip button').trigger('click')
    await flushPromises()
    expect(command).toHaveBeenLastCalledWith(account.id, scope.groupId, expect.objectContaining({
      action: 'update',
      expectedOnboardingRevision: 3,
      expectedAssignmentRevision: 1,
      previewDigest: 'digest-preview-update',
    }))

    const lifecycleButton = (label: string) => wrapper.findAll('.lifecycle-actions button').find((button) => button.text().includes(label))!
    await lifecycleButton('暂停').trigger('click')
    await flushPromises()
    await lifecycleButton('恢复').trigger('click')
    await flushPromises()
    await lifecycleButton('回滚').trigger('click')
    await flushPromises()

    expect(command.mock.calls.map(([, , request]) => request.action)).toEqual([
      'activate',
      'update',
      'pause',
      'resume',
      'rollback',
    ])
    expect(wrapper.get('.assignment-section').text()).toContain('rolled_back')
    expect(wrapper.get('.receipt-strip').text()).toContain('已回滚到稳定版本')

    await wrapper.get('.view-header .icon-button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.assignment-section').text()).toContain('rolled_back')
    expect(wrapper.get('.pending-list').text()).toContain('群 345678901')
  })
})
