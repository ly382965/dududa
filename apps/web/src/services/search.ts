import PinyinMatch from 'pinyin-match'

export function createSearchMatcher(query: string): (value: string) => boolean {
  const normalized = query.normalize('NFKC').trim().toLocaleLowerCase('zh-CN')
  if (!normalized) return () => true
  const terms = normalized.split(/\s+/).filter(Boolean)
  return (value) => {
    const candidate = value.normalize('NFKC').toLocaleLowerCase('zh-CN')
    return terms.every((term) => candidate.includes(term) || PinyinMatch.match(candidate, term) !== false)
  }
}
