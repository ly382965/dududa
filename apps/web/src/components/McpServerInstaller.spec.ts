import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mcpManagementAdapter } from '../services/mcp-management'
import McpServerInstaller from './McpServerInstaller.vue'

vi.mock('../services/mcp-management', () => ({
  mcpManagementAdapter: { install: vi.fn() },
}))

describe('McpServerInstaller', () => {
  beforeEach(() => vi.mocked(mcpManagementAdapter.install).mockReset())

  it('submits a structured HTTP definition without granting a Capability', async () => {
    vi.mocked(mcpManagementAdapter.install).mockResolvedValue({
      schemaVersion: 1,
      status: 'ok',
      server: { id: 'campus-news', displayName: '校园资讯' },
      discovery: { status: 'ok', tools: [{ name: 'news_list' }] },
      capabilityGranted: false,
      message: 'MCP Server 已登记',
    })
    const wrapper = mount(McpServerInstaller, { global: { stubs: { Teleport: true } } })

    await wrapper.get('button[title="接入 MCP Server"]').trigger('click')
    await wrapper.get('input[placeholder="campus-news"]').setValue('campus-news')
    await wrapper.get('input[placeholder="校园资讯"]').setValue('校园资讯')
    await wrapper.get('input[placeholder="https://mcp.example.edu/mcp"]').setValue('https://mcp.example.edu/mcp')
    await wrapper.get('textarea[placeholder^="每行或逗号分隔"]').setValue('news_list, news_get')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mcpManagementAdapter.install).toHaveBeenCalledWith(expect.objectContaining({
      serverId: 'campus-news',
      transport: 'streamable_http',
      endpoint: {
        url: 'https://mcp.example.edu/mcp',
        allowedHosts: ['mcp.example.edu'],
      },
      allowedTools: ['news_list', 'news_get'],
      secretRefs: [],
    }))
    expect(wrapper.emitted('installed')).toHaveLength(1)
    expect(wrapper.text()).toContain('尚未授予 Agent Capability')
  })
})
