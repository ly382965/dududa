import type {
  ControlPlaneStatus,
  GroupServiceCommandRequest,
  GroupServiceCommandResponse,
  ManagedGroups,
  PendingInbox,
  PreviewRequest,
  PreviewResponse,
  ProfileCatalog,
} from '../src/types/control-plane'

export interface ControlPlaneClient {
  status(): ControlPlaneStatus
  pendingInbox(sessionRef: string, platform: string, botId: string): Promise<PendingInbox>
  managedGroups(sessionRef: string, platform: string, botId: string): Promise<ManagedGroups>
  profileCatalog(sessionRef: string, platform: string, botId: string): Promise<ProfileCatalog>
  preview(
    sessionRef: string,
    platform: string,
    botId: string,
    groupId: string,
    request: PreviewRequest,
  ): Promise<PreviewResponse>
  command(
    sessionRef: string,
    platform: string,
    botId: string,
    groupId: string,
    request: GroupServiceCommandRequest,
  ): Promise<GroupServiceCommandResponse>
}

export class ControlPlaneClientError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ControlPlaneClientError'
  }
}

export class UnavailableControlPlaneClient implements ControlPlaneClient {
  constructor(private readonly reason = 'Bot Control Plane 后端未配置') {}

  status(): ControlPlaneStatus {
    return { available: false, reason: this.reason }
  }

  async pendingInbox(): Promise<PendingInbox> {
    throw new ControlPlaneClientError(this.reason, 503)
  }

  async managedGroups(): Promise<ManagedGroups> {
    throw new ControlPlaneClientError(this.reason, 503)
  }

  async profileCatalog(): Promise<ProfileCatalog> {
    throw new ControlPlaneClientError(this.reason, 503)
  }

  async preview(): Promise<PreviewResponse> {
    throw new ControlPlaneClientError(this.reason, 503)
  }

  async command(): Promise<GroupServiceCommandResponse> {
    throw new ControlPlaneClientError(this.reason, 503)
  }
}

export class HttpControlPlaneClient implements ControlPlaneClient {
  private readonly baseUrl: string

  constructor(baseUrl: string, private readonly timeoutMs = 10_000) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Control Plane URL 协议无效')
    this.baseUrl = parsed.toString().replace(/\/$/, '')
  }

  status(): ControlPlaneStatus {
    return { available: true }
  }

  async pendingInbox(sessionRef: string, platform: string, botId: string): Promise<PendingInbox> {
    return this.request(
      `/v1/control-plane/${encodeURIComponent(platform)}/bots/${encodeURIComponent(botId)}/pending`,
      sessionRef,
    )
  }

  async managedGroups(sessionRef: string, platform: string, botId: string): Promise<ManagedGroups> {
    return this.request(
      `/v1/control-plane/${encodeURIComponent(platform)}/bots/${encodeURIComponent(botId)}/managed`,
      sessionRef,
    )
  }

  async profileCatalog(sessionRef: string, platform: string, botId: string): Promise<ProfileCatalog> {
    return this.request(
      `/v1/control-plane/${encodeURIComponent(platform)}/bots/${encodeURIComponent(botId)}/profiles`,
      sessionRef,
    )
  }

  async preview(
    sessionRef: string,
    platform: string,
    botId: string,
    groupId: string,
    request: PreviewRequest,
  ): Promise<PreviewResponse> {
    return this.request(this.groupPath(platform, botId, groupId, 'preview'), sessionRef, request)
  }

  async command(
    sessionRef: string,
    platform: string,
    botId: string,
    groupId: string,
    request: GroupServiceCommandRequest,
  ): Promise<GroupServiceCommandResponse> {
    return this.request(this.groupPath(platform, botId, groupId, 'commands'), sessionRef, request)
  }

  private groupPath(platform: string, botId: string, groupId: string, suffix: string): string {
    return `/v1/control-plane/${encodeURIComponent(platform)}/bots/${encodeURIComponent(botId)}` +
      `/groups/${encodeURIComponent(groupId)}/${suffix}`
  }

  private async request<T>(path: string, sessionRef: string, payload?: object): Promise<T> {
    if (!sessionRef.trim()) throw new ControlPlaneClientError('管理员会话缺失', 401)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    timer.unref?.()
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: payload ? 'POST' : 'GET',
        headers: {
          Accept: 'application/json',
          'X-Dududa-Operator-Session': sessionRef,
          ...(payload ? { 'Content-Type': 'application/json' } : {}),
        },
        body: payload ? JSON.stringify(payload) : undefined,
        signal: controller.signal,
      })
      const body = await response.json().catch(() => ({})) as { error?: string }
      if (!response.ok) {
        throw new ControlPlaneClientError(body.error || `Control Plane 请求失败: ${response.status}`, response.status)
      }
      return body as T
    } catch (error) {
      if (error instanceof ControlPlaneClientError) throw error
      throw new ControlPlaneClientError(
        error instanceof Error && error.name === 'AbortError' ? 'Control Plane 请求超时' : 'Control Plane 后端不可用',
        503,
      )
    } finally {
      clearTimeout(timer)
    }
  }
}
