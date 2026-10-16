import { apiGet } from './request'

interface ApiBaseResponse {
  success: boolean
  error?: string
}

function checkSuccess(response: ApiBaseResponse, errorMsg: string): void {
  if (!response.success) {
    throw new Error(response.error || errorMsg)
  }
}

export async function getAllStats(): Promise<any> {
  const response = await apiGet<any>('stats/all')
  checkSuccess(response, '获取统计失败')
  return {
    memory: response.memory || { l1: {}, l2: {}, l3: {} },
    token: response.token || {},
    kg: response.kg || { node_count: 0, edge_count: 0, node_types: {}, relation_types: {} },
    system: response.system || { components: { l1_buffer: false, l2_memory: false, l3_kg: false, profile: false, llm_manager: false }, uptime: 0 }
  }
}

export async function getTokenStats(): Promise<any> {
  const response = await apiGet<any>('stats/token')
  checkSuccess(response, '获取Token统计失败')
  return response.stats || {}
}

export async function getMemoryStats(): Promise<any> {
  const response = await apiGet<any>('stats/memory')
  checkSuccess(response, '获取记忆统计失败')
  return response.stats || { l1: {}, l2: {}, l3: {} }
}

export async function getKGStats(): Promise<any> {
  const response = await apiGet<any>('stats/kg')
  checkSuccess(response, '获取图谱统计失败')
  return response.stats || { node_count: 0, edge_count: 0, node_types: {}, relation_types: {} }
}

export async function getSystemStats(): Promise<any> {
  const response = await apiGet<any>('stats/system')
  checkSuccess(response, '获取系统统计失败')
  return response.stats || { components: { l1_buffer: false, l2_memory: false, l3_kg: false, profile: false, llm_manager: false }, uptime: 0 }
}
