/** Keep every character, preferring paragraph/sentence boundaries for QQ nodes. */
export const SUMMARY_FORWARD_THRESHOLD = 1000

export function summaryForwardParts(text: string): string[] {
  const characters = Array.from(text)
  const parts: string[] = []
  let offset = 0
  while (offset < characters.length) {
    let end = Math.min(offset + SUMMARY_FORWARD_THRESHOLD, characters.length)
    if (end < characters.length) {
      for (let index = end - 1; index >= offset + SUMMARY_FORWARD_THRESHOLD / 2; index--) {
        if ('\n。！？'.includes(characters[index]!)) {
          end = index + 1
          break
        }
      }
    }
    parts.push(characters.slice(offset, end).join(''))
    offset = end
  }
  return parts
}
