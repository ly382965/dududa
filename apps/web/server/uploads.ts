import type { IncomingMessage } from 'node:http'
import { Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'

import Busboy from 'busboy'

export interface BrowserUpload {
  buffer: Buffer
  fileName: string
  mime: string
  size: number
}

function safeFileName(value: string): string {
  const normalized = value
    .replace(/[\\/\u0000-\u001f\u007f]/g, '_')
    .trim()
    .slice(0, 255)
  return normalized || '未命名文件'
}

export async function readBrowserUpload(
  request: IncomingMessage,
  maxBytes = 25 * 1024 * 1024,
): Promise<BrowserUpload> {
  const contentType = request.headers['content-type'] ?? ''
  if (!contentType.toLowerCase().startsWith('multipart/form-data;')) {
    throw new Error('上传请求必须使用 multipart/form-data')
  }
  const totalLimit = maxBytes + 64 * 1024
  const contentLength = Number(request.headers['content-length'] ?? 0)
  if (Number.isFinite(contentLength) && contentLength > totalLimit) throw new Error('上传请求超过总大小限制')

  let parser: ReturnType<typeof Busboy>
  try {
    parser = Busboy({
      headers: request.headers,
      defParamCharset: 'utf8',
      limits: { files: 1, fields: 0, parts: 1, fileSize: maxBytes },
    })
  } catch {
    throw new Error('上传请求格式无效')
  }

  let upload: BrowserUpload | undefined
  let failure = ''
  parser.on('file', (_field, stream, info) => {
    const chunks: Buffer[] = []
    let size = 0
    stream.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size <= maxBytes) chunks.push(chunk)
    })
    stream.once('limit', () => {
      failure = '上传文件超过 25 MB 上限'
    })
    stream.once('error', () => {
      failure ||= '上传请求解析失败'
    })
    stream.once('end', () => {
      if (failure) return
      upload = {
        buffer: Buffer.concat(chunks),
        fileName: safeFileName(info.filename),
        mime: info.mimeType.slice(0, 128) || 'application/octet-stream',
        size,
      }
    })
  })
  parser.once('filesLimit', () => {
    failure = '一次只能上传一个文件'
  })

  let totalBytes = 0
  const limiter = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      totalBytes += chunk.length
      if (totalBytes > totalLimit) callback(new Error('upload request too large'))
      else callback(null, chunk)
    },
  })
  try {
    await pipeline(request, limiter, parser)
  } catch {
    if (totalBytes > totalLimit) throw new Error('上传请求超过总大小限制')
    throw new Error(failure || (request.destroyed ? '上传请求已中断' : '上传请求解析失败'))
  }
  if (failure) throw new Error(failure)
  if (!upload || upload.size <= 0) throw new Error('上传文件为空')
  return upload
}
