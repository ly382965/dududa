import { describe, expect, it } from 'vitest'

import { renderMarkdown } from './markdown'

describe('safe markdown', () => {
  it('escapes HTML and rejects javascript links', () => {
    const html = renderMarkdown('<script>alert(1)</script> [bad](javascript:alert(1)) [good](https://example.com)')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('rel="noopener noreferrer nofollow"')
  })
})
