import MarkdownIt from 'markdown-it'

const renderer = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: false })

const defaultLinkOpen =
  renderer.renderer.rules.link_open ??
  ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options))

renderer.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index]?.attrSet('target', '_blank')
  tokens[index]?.attrSet('rel', 'noopener noreferrer nofollow')
  return defaultLinkOpen(tokens, index, options, env, self)
}

export function renderMarkdown(value: string): string {
  return renderer.render(value.slice(0, 64 * 1024))
}

export function linkifiedTextParts(value: string): Array<{ text: string; href?: string }> {
  const matches = renderer.linkify.match(value)
  if (!matches) return [{ text: value }]
  const parts: Array<{ text: string; href?: string }> = []
  let cursor = 0
  for (const match of matches) {
    const href = renderer.normalizeLink(match.url)
    if (!renderer.validateLink(href)) continue
    if (match.index > cursor) parts.push({ text: value.slice(cursor, match.index) })
    parts.push({ text: value.slice(match.index, match.lastIndex), href })
    cursor = match.lastIndex
  }
  if (cursor < value.length) parts.push({ text: value.slice(cursor) })
  return parts.length ? parts : [{ text: value }]
}
