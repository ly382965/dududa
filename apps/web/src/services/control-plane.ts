import type {
  ControlPlaneStatus,
  GroupServiceCommandRequest,
  GroupServiceCommandResponse,
  ManagedGroups,
  PendingInbox,
  PreviewRequest,
  PreviewResponse,
  ProfileCatalog,
} from '../types/control-plane'

export interface ControlPlaneAdapter {
  status(): Promise<ControlPlaneStatus>
  pendingInbox(accountId: string): Promise<PendingInbox>
  managedGroups(accountId: string): Promise<ManagedGroups>
  profileCatalog(accountId: string): Promise<ProfileCatalog>
  preview(accountId: string, groupId: string, request: PreviewRequest): Promise<PreviewResponse>
  command(
    accountId: string,
    groupId: string,
    request: GroupServiceCommandRequest,
  ): Promise<GroupServiceCommandResponse>
}

export class HttpControlPlaneAdapter implements ControlPlaneAdapter {
  constructor(
    private readonly baseUrl = '',
    private readonly sessionRef = () => window.sessionStorage.getItem('dududa-operator-session') ?? '',
  ) {}

  status(): Promise<ControlPlaneStatus> {
    return this.request('/api/control-plane/status', false)
  }

  pendingInbox(accountId: string): Promise<PendingInbox> {
    return this.request(`${this.accountPath(accountId)}/pending`, true)
  }

  managedGroups(accountId: string): Promise<ManagedGroups> {
    return this.request(`${this.accountPath(accountId)}/managed`, true)
  }

  profileCatalog(accountId: string): Promise<ProfileCatalog> {
    return this.request(`${this.accountPath(accountId)}/profiles`, true)
  }

  preview(accountId: string, groupId: string, request: PreviewRequest): Promise<PreviewResponse> {
    return this.request(
      `${this.accountPath(accountId)}/groups/${encodeURIComponent(groupId)}/preview`,
      true,
      request,
    )
  }

  command(
    accountId: string,
    groupId: string,
    request: GroupServiceCommandRequest,
  ): Promise<GroupServiceCommandResponse> {
    return this.request(
      `${this.accountPath(accountId)}/groups/${encodeURIComponent(groupId)}/commands`,
      true,
      request,
    )
  }

  private accountPath(accountId: string): string {
    return `/api/control-plane/accounts/${encodeURIComponent(accountId)}`
  }

  private async request<T>(path: string, authenticated: boolean, payload?: object): Promise<T> {
    const session = authenticated ? this.sessionRef().trim() : ''
    if (authenticated && !session) throw new Error('管理员会话不可用')
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: payload ? 'POST' : 'GET',
      headers: {
        Accept: 'application/json',
        ...(session ? { 'X-Dududa-Operator-Session': session } : {}),
        ...(payload ? { 'Content-Type': 'application/json' } : {}),
      },
      body: payload ? JSON.stringify(payload) : undefined,
    })
    const body = await response.json().catch(() => ({})) as { error?: string }
    if (!response.ok) throw new Error(body.error || `Control Plane 请求失败: ${response.status}`)
    return body as T
  }
}

export const controlPlaneAdapter = new HttpControlPlaneAdapter()
