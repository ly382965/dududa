import { readonly, ref, shallowRef } from 'vue'
import { z } from 'zod'

const QQ_FACE_BASE_URL = 'https://koishi.js.org/QFace/'

const QqFaceIndexSchema = z.array(
  z.object({
    emojiId: z.string(),
    describe: z.string().catch(''),
    isHide: z.boolean().catch(false),
    assets: z
      .array(z.object({ type: z.number(), name: z.string(), path: z.string() }))
      .catch([]),
  }),
)

type QqFaceFormat = 'png' | 'apng' | 'large' | 'lottie'

export interface QqFaceDefinition {
  id: string
  name: string
  pngUrl: string
  apngUrl?: string
  largePngUrl?: string
  lottieUrl?: string
}

interface QqFaceCatalog {
  yellowFaces: QqFaceDefinition[]
  superFaces: QqFaceDefinition[]
  emojiFaces: QqFaceDefinition[]
}

const emptyCatalog = (): QqFaceCatalog => ({ yellowFaces: [], superFaces: [], emojiFaces: [] })
const catalog = shallowRef<QqFaceCatalog>(emptyCatalog())
const catalogById = shallowRef(new Map<string, QqFaceDefinition>())
const loading = ref(false)
const error = ref('')
let catalogRequest: Promise<QqFaceCatalog> | null = null

export const qqFaceCatalog = readonly(catalog)
export const qqFaceCatalogLoading = readonly(loading)
export const qqFaceCatalogError = readonly(error)

function assetUrl(path: string): string {
  return new URL(path, QQ_FACE_BASE_URL).href
}

export async function loadQqFaceCatalog(force = false): Promise<QqFaceCatalog> {
  if (!force && catalogById.value.size) return catalog.value
  if (catalogRequest) return catalogRequest
  loading.value = true
  error.value = ''
  catalogRequest = (async () => {
    const response = await fetch(`${QQ_FACE_BASE_URL}assets/qq_emoji/_index.json`)
    if (!response.ok) throw new Error(`QFace index request failed with ${response.status}`)
    const entries = QqFaceIndexSchema.parse(await response.json())
    const definitions = new Map<string, QqFaceDefinition>()
    const visible: QqFaceDefinition[] = []
    const staticEmojiIds = new Set<string>()
    for (const entry of entries) {
      const staticAssets = entry.assets.filter((asset) => asset.type === 0)
      const png =
        staticAssets.find((asset) => asset.name === `${entry.emojiId}.png`) ??
        staticAssets.find((asset) => !asset.name.endsWith('_0.png')) ??
        staticAssets[0]
      const apng = entry.assets.find((asset) => asset.type === 2)
      const lottie = entry.assets.find((asset) => asset.type === 3)
      const largePng = staticAssets.find(
        (asset) => asset.name === `${entry.emojiId}_0.png` || asset.name.endsWith('_0.png'),
      )
      if (!png && !apng) continue
      const face: QqFaceDefinition = {
        id: entry.emojiId,
        name: entry.describe.replace(/^\//u, '').trim() || `#${entry.emojiId}`,
        pngUrl: assetUrl((png ?? apng)!.path),
        ...(apng ? { apngUrl: assetUrl(apng.path) } : {}),
        ...(largePng ? { largePngUrl: assetUrl(largePng.path) } : {}),
        ...(lottie ? { lottieUrl: assetUrl(lottie.path) } : {}),
      }
      definitions.set(face.id, face)
      if (!entry.isHide) {
        visible.push(face)
        if (!apng && !lottie) staticEmojiIds.add(face.id)
      }
    }
    const nextCatalog = {
      yellowFaces: visible.filter((face) => face.apngUrl),
      superFaces: visible.filter((face) => face.lottieUrl && face.largePngUrl),
      emojiFaces: visible.filter((face) => staticEmojiIds.has(face.id)),
    }
    catalogById.value = definitions
    catalog.value = nextCatalog
    return nextCatalog
  })()
  try {
    return await catalogRequest
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'QQ 表情目录加载失败'
    throw cause
  } finally {
    catalogRequest = null
    loading.value = false
  }
}

export function qqFaceUrl(faceId: string, format: QqFaceFormat = 'png'): string {
  const face = catalogById.value.get(faceId)
  if (face) {
    if (format === 'large') return face.largePngUrl || face.apngUrl || face.pngUrl
    if (format === 'lottie') return face.lottieUrl || ''
    if (format === 'apng') return face.apngUrl || face.pngUrl
    return face.pngUrl
  }
  const encodedId = encodeURIComponent(faceId)
  if (format === 'large') return `${QQ_FACE_BASE_URL}assets/qq_emoji/${encodedId}/png/${encodedId}_0.png`
  if (format === 'lottie') return `${QQ_FACE_BASE_URL}assets/qq_emoji/${encodedId}/lottie/${encodedId}.json`
  return `${QQ_FACE_BASE_URL}assets/qq_emoji/${encodedId}/${format}/${encodedId}.png`
}
