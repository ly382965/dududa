import { PassThrough } from 'node:stream'

import { describe, expect, it } from 'vitest'

import { readBrowserUpload } from './uploads'

function multipart(body: Buffer, boundary: string): PassThrough & { headers: Record<string, string> } {
  const request = new PassThrough() as PassThrough & { headers: Record<string, string> }
  request.headers = { 'content-type': `multipart/form-data; boundary=${boundary}` }
  request.end(body)
  return request
}

describe('browser upload parser', () => {
  it('reads one bounded file and strips path/control characters', async () => {
    const boundary = 'dududa-upload-boundary'
    const body = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="../unsafe\\name.txt"\r\nContent-Type: text/plain\r\n\r\nreal data\r\n--${boundary}--\r\n`,
    )

    await expect(readBrowserUpload(multipart(body, boundary) as never, 1024)).resolves.toMatchObject({
      fileName: 'name.txt',
      mime: 'text/plain',
      size: 9,
      buffer: Buffer.from('real data'),
    })
  })

  it('rejects oversized and non-multipart input', async () => {
    const boundary = 'dududa-upload-boundary'
    const body = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.txt"\r\nContent-Type: text/plain\r\n\r\n123456\r\n--${boundary}--\r\n`,
    )
    await expect(readBrowserUpload(multipart(body, boundary) as never, 3)).rejects.toThrow('超过')

    const request = new PassThrough() as PassThrough & { headers: Record<string, string> }
    request.headers = { 'content-type': 'application/json' }
    request.end('{}')
    await expect(readBrowserUpload(request as never)).rejects.toThrow('multipart/form-data')
  })

  it('rejects truncated streams and bounds the complete multipart request', async () => {
    const boundary = 'dududa-upload-boundary'
    const truncated = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="broken.txt"\r\nContent-Type: text/plain\r\n\r\nincomplete`,
    )
    await expect(readBrowserUpload(multipart(truncated, boundary) as never, 1024)).rejects.toThrow('上传请求解析失败')

    const padded = Buffer.concat([
      Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="ignored"\r\n\r\n`),
      Buffer.alloc(70 * 1024, 97),
    ])
    await expect(readBrowserUpload(multipart(padded, boundary) as never, 3)).rejects.toThrow('总大小限制')
  })
})
