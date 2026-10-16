import type { ApiKeyProbe, ApiKeyProbeContext, ApiKeyProbeResult } from './model-keys'

/**
 * Build the small, explicit connectivity probe used by the production Web
 * gateway.  The probe is invoked only after an operator clicks “探测
 * Provider”; it never runs in the request or Runtime hot path.  Response
 * bodies are discarded so an upstream error cannot echo a credential or a
 * prompt back to the control plane.
 */
export function createHttpApiKeyProbe(fetchImpl: typeof fetch = fetch): ApiKeyProbe {
  return async (context: ApiKeyProbeContext): Promise<ApiKeyProbeResult> => {
    const protocol = normalizeProtocol(context.pool.protocol)
    if (!protocol) {
      return { ok: false, status: 'error', message: '暂不支持此 Provider 协议' }
    }
    let target: string
    try {
      target = endpointUrl(context.pool.baseUrl, protocol)
    } catch {
      return { ok: false, status: 'error', message: 'Provider Base URL 无效' }
    }

    const headers = new Headers({
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'User-Agent': 'Dududa-API-Key-Probe/1.0',
    })
    // Custom headers are already validated by the store and are deliberately
    // limited to non-authentication values.  Protocol authentication is set
    // after them so a stale custom value cannot replace the tested key.
    for (const header of context.pool.customHeaders) headers.set(header.name, header.value)
    if (protocol === 'anthropic_messages') {
      headers.set('x-api-key', context.secret)
      headers.set('anthropic-version', '2023-06-01')
    } else {
      headers.set('Authorization', `Bearer ${context.secret}`)
    }

    const body = JSON.stringify(requestBody(context.pool.model, protocol))
    let response: Response
    try {
      response = await fetchImpl(target, {
        method: 'POST',
        headers,
        body,
        // Do not follow a redirect with an Authorization header.  A provider
        // can still explicitly return a non-2xx response for the operator.
        redirect: 'error',
        signal: context.signal,
      })
    } catch (error) {
      // Preserve AbortError for FileApiKeyPoolStore's bounded timeout path.
      if (context.signal.aborted || (error instanceof Error && error.name === 'AbortError')) throw error
      return { ok: false, status: 'error', message: 'Provider 连接失败' }
    }
    try {
      const ok = response.ok
      return {
        ok,
        status: ok ? 'ok' : 'error',
        message: ok ? 'Provider 探测成功' : `Provider 返回 HTTP ${response.status}`,
        model: context.pool.model,
      }
    } finally {
      await response.body?.cancel().catch(() => undefined)
    }
  }
}

type ProbeProtocol = 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages'

function normalizeProtocol(value: string): ProbeProtocol | undefined {
  const normalized = value.trim().toLowerCase().replace(/-/g, '_')
  if (['openai', 'chat_completion', 'openai_chat_completion', 'openai_chat_completions'].includes(normalized)) {
    return 'openai_chat_completions'
  }
  if (['responses', 'openai_response', 'openai_responses'].includes(normalized)) return 'openai_responses'
  if (['anthropic', 'anthropic_message', 'anthropic_messages'].includes(normalized)) return 'anthropic_messages'
  return undefined
}

function endpointUrl(baseUrl: string, protocol: ProbeProtocol): string {
  const parsed = new URL(baseUrl)
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('invalid provider URL')
  }
  const suffix = protocol === 'openai_responses'
    ? '/responses'
    : protocol === 'anthropic_messages'
      ? '/messages'
      : '/chat/completions'
  const pathname = parsed.pathname.replace(/\/+$/, '')
  if (pathname.endsWith(suffix)) return parsed.toString()
  parsed.pathname = `${pathname}${suffix}` || suffix
  return parsed.toString()
}

function requestBody(model: string, protocol: ProbeProtocol): Record<string, unknown> {
  if (protocol === 'openai_responses') {
    return { model, input: 'Reply with OK only.', max_output_tokens: 8, store: false }
  }
  if (protocol === 'anthropic_messages') {
    return { model, max_tokens: 8, messages: [{ role: 'user', content: 'Reply with OK only.' }] }
  }
  return {
    model,
    messages: [{ role: 'user', content: 'Reply with OK only.' }],
    max_tokens: 8,
    stream: false,
  }
}
