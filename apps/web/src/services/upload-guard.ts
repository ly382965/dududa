const storageKey = 'dududa-uncertain-group-uploads-v1'
const guardTtlMs = 10 * 60_000

function storage(): Storage | undefined {
  try {
    return typeof window !== 'undefined' ? window.localStorage : undefined
  } catch {
    return undefined
  }
}

function entries(target: Storage | undefined, now: number): Record<string, number> {
  if (!target) return {}
  try {
    const parsed = JSON.parse(target.getItem(storageKey) || '{}') as Record<string, unknown>
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([key, value]) =>
        typeof value === 'number' && Number.isFinite(value) && value > now ? [[key, value]] : [],
      ),
    )
  } catch {
    return {}
  }
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((value) => value.toString(16).padStart(2, '0')).join('')
}

export async function groupUploadFingerprint(
  accountId: string,
  groupId: string,
  parentId: string,
  file: File,
): Promise<string> {
  // Copy into this realm so WebCrypto accepts File buffers from jsdom and embedded WebViews.
  const contentBytes = Uint8Array.from(new Uint8Array(await file.arrayBuffer()))
  const contentDigest = await crypto.subtle.digest('SHA-256', contentBytes)
  const scope = new TextEncoder().encode(
    `${accountId}\0${groupId}\0${parentId}\0${file.name}\0${file.size}\0${hex(contentDigest)}`,
  )
  return hex(await crypto.subtle.digest('SHA-256', scope))
}

export function uncertainGroupUploadBlocked(
  fingerprint: string,
  now = Date.now(),
  target = storage(),
): boolean {
  const current = entries(target, now)
  try {
    if (target) target.setItem(storageKey, JSON.stringify(current))
  } catch {
    // markUncertainGroupUpload will stop a new upload when persistence is unavailable.
  }
  return (current[fingerprint] ?? 0) > now
}

export function markUncertainGroupUpload(
  fingerprint: string,
  now = Date.now(),
  target = storage(),
): boolean {
  if (!target) return false
  const current = entries(target, now)
  current[fingerprint] = now + guardTtlMs
  try {
    target.setItem(storageKey, JSON.stringify(current))
    return true
  } catch {
    return false
  }
}

export function clearUncertainGroupUpload(
  fingerprint: string,
  now = Date.now(),
  target = storage(),
): void {
  if (!target) return
  const current = entries(target, now)
  delete current[fingerprint]
  try {
    target.setItem(storageKey, JSON.stringify(current))
  } catch {
    // A stale guard is safer than reporting a successful QQ upload as failed.
  }
}
