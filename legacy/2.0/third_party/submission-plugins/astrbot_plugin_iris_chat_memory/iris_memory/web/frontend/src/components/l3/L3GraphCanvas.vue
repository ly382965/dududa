<template>
  <div class="canvas-wrapper">
    <!-- 顶部工具栏 -->
    <div class="canvas-toolbar">
      <div class="toolbar-left">
        <v-btn-group density="compact" variant="tonal">
          <v-btn
            icon="mdi-undo-variant"
            size="small"
            :disabled="!canGoBack"
            @click="emit('nav-back')"
          >
            <v-tooltip activator="parent" location="bottom">后退</v-tooltip>
          </v-btn>
          <v-btn
            icon="mdi-redo-variant"
            size="small"
            :disabled="!canGoForward"
            @click="emit('nav-forward')"
          >
            <v-tooltip activator="parent" location="bottom">前进</v-tooltip>
          </v-btn>
        </v-btn-group>

        <v-btn-group density="compact" variant="tonal" class="ml-2">
          <v-btn icon="mdi-magnify-plus" size="small" @click="zoomBy(1.25)" />
          <v-btn icon="mdi-magnify-minus" size="small" @click="zoomBy(0.8)" />
          <v-btn icon="mdi-fit-to-screen" size="small" @click="fitView" />
          <v-btn icon="mdi-image-filter-center-focus" size="small" @click="fitCenter" />
        </v-btn-group>

        <v-chip v-if="startNode" size="small" color="accent" variant="tonal" class="ml-2">
          <v-icon :icon="getNodeIcon(startNode.label)" start size="small" />
          {{ startNode.name }}
        </v-chip>
      </div>

      <div class="toolbar-right">
        <v-chip size="small" variant="text">
          <v-icon icon="mdi-circle-multiple" start size="small" color="primary" />
          {{ nodes.length }}
        </v-chip>
        <v-chip size="small" variant="text">
          <v-icon icon="mdi-arrow-right-bold" start size="small" color="secondary" />
          {{ edges.length }}
        </v-chip>
      </div>
    </div>

    <!-- G6 画布容器 -->
    <div ref="containerRef" class="graph-container">
      <div v-if="loading" class="overlay">
        <v-progress-circular indeterminate color="primary" size="56" width="4" />
        <div class="text-caption mt-3 text-medium-emphasis">加载图谱中…</div>
      </div>
      <div v-else-if="nodes.length === 0" class="overlay">
        <v-icon icon="mdi-graph-outline" size="72" class="mb-3 text-medium-emphasis" />
        <div class="text-h6 text-medium-emphasis">暂无图谱数据</div>
        <div class="text-body-2 text-medium-emphasis mt-1">
          L3 知识图谱为空或未启用
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Graph } from '@antv/g6'
import type { GraphData, NodeData, EdgeData } from '@antv/g6'
import type { KGNode, KGEdge, L3LayoutType } from '@/types'
import {
  getNodeIcon,
  getTypeColor,
  getRelationLabel,
  resolveThemeColor,
} from '@/composables/l3Constants'

const props = defineProps<{
  nodes: KGNode[]
  edges: KGEdge[]
  loading: boolean
  startNode: KGNode | null
  layout: L3LayoutType
  canGoBack: boolean
  canGoForward: boolean
}>()

const emit = defineEmits<{
  'node-click': [node: KGNode]
  'node-dblclick': [nodeId: string]
  'edge-click': [edge: KGEdge]
  'nav-back': []
  'nav-forward': []
}>()

const containerRef = ref<HTMLElement | null>(null)
const graphRef = shallowRef<Graph | null>(null)
let resizeObserver: ResizeObserver | null = null

// ---- 主题色缓存（canvas 无法消费 CSS 变量）----
const colorCache = new Map<string, string>()
const nodeFill = (label: string): string => {
  if (!colorCache.has(label)) {
    colorCache.set(label, resolveThemeColor(getTypeColor(label), '#5c6bc0'))
  }
  return colorCache.get(label)!
}

// ---- 计算节点度数（用于节点大小映射）----
const computeDegrees = (): Map<string, number> => {
  const deg = new Map<string, number>()
  props.edges.forEach((e) => {
    deg.set(e.source, (deg.get(e.source) || 0) + 1)
    deg.set(e.target, (deg.get(e.target) || 0) + 1)
  })
  return deg
}

// ---- 布局配置 ----
const layoutConfig = (type: L3LayoutType) => {
  switch (type) {
    case 'dagre':
      return {
        type: 'dagre',
        rankdir: 'LR',
        nodesep: 20,
        ranksep: 50,
        preventOverlap: true,
      } as any
    case 'radial':
      return {
        type: 'radial',
        unitRadius: 100,
        preventOverlap: true,
        nodeSize: 36,
        linkDistance: 140,
      } as any
    case 'concentric':
      return {
        type: 'concentric',
        minNodeSpacing: 30,
        preventOverlap: true,
        nodeSize: 36,
      } as any
    case 'force':
    default:
      return {
        type: 'force',
        preventOverlap: true,
        nodeSize: 36,
        linkDistance: 140,
        nodeStrength: -60,
        edgeStrength: 0.7,
        gravity: 8,
        alpha: 0.3,
        alphaDecay: 0.028,
        alphaMin: 0.001,
      } as any
  }
}

// ---- 数据转换 ----
const toGraphData = (): GraphData => {
  const degrees = computeDegrees()
  const maxDeg = Math.max(1, ...degrees.values())
  return {
    nodes: props.nodes.map<NodeData>((n) => {
      const deg = degrees.get(n.id) || 0
      // 度数越大节点越大：24 ~ 44
      const size = 24 + (deg / maxDeg) * 20
      return {
        id: n.id,
        data: {
          label: n.label,
          name: n.name,
          confidence: n.confidence,
          degree: deg,
          size,
        },
      }
    }),
    edges: props.edges.map<EdgeData>((e) => ({
      source: e.source,
      target: e.target,
      data: { relation: e.relation, weight: e.weight ?? 1 },
    })),
  }
}

// ---- 初始化 G6 ----
const initGraph = () => {
  const container = containerRef.value
  if (!container) return
  const width = container.clientWidth || 800
  const height = container.clientHeight || 500

  const graph = new Graph({
    container,
    width,
    height,
    autoFit: 'view',
    data: toGraphData(),
    layout: layoutConfig(props.layout),
    node: {
      type: 'circle',
      style: (d: NodeData) => {
        const label = (d.data?.label as string) || 'Entity'
        const name = (d.data?.name as string) || String(d.id)
        const size = (d.data?.size as number) || 30
        return {
          size,
          fill: nodeFill(label),
          stroke: '#ffffff',
          lineWidth: 2,
          labelText: name,
          labelPlacement: 'bottom',
          labelFontSize: 11,
          labelFill: '#424242',
          labelBackground: true,
          labelBackgroundFill: 'rgba(255,255,255,0.85)',
          labelBackgroundOpacity: 0.9,
          labelPadding: [2, 4],
          cursor: 'pointer',
        }
      },
      state: {
        active: {
          lineWidth: 3,
          stroke: '#ff9800',
          shadowColor: 'rgba(255,152,0,0.6)',
          shadowBlur: 12,
        },
        inactive: { opacity: 0.2 },
        selected: { lineWidth: 3, stroke: '#ff9800' },
      },
    },
    edge: {
      type: 'line',
      style: (d: EdgeData) => {
        const w = (d.data?.weight as number) ?? 1
        return {
          stroke: '#9e9e9e',
          lineWidth: 1 + w,
          strokeOpacity: 0.7,
          endArrow: true,
          labelText: getRelationLabel((d.data?.relation as string) || ''),
          labelFontSize: 9,
          labelFill: '#616161',
          labelBackground: true,
          labelBackgroundFill: 'rgba(255,255,255,0.85)',
          labelBackgroundOpacity: 0.9,
          labelPadding: [1, 3],
          cursor: 'pointer',
        }
      },
      state: {
        active: { stroke: '#ff9800', lineWidth: 2.5, strokeOpacity: 1 },
        inactive: { opacity: 0.1 },
      },
    },
    behaviors: [
      'zoom-canvas',
      'drag-canvas',
      'drag-element',
      {
        type: 'hover-activate',
        degree: 1,
        state: 'active',
        inactiveState: 'inactive',
      },
    ],
    plugins: [
      {
        type: 'minimap',
        size: [180, 120],
        position: 'right-bottom',
        className: 'l3-minimap',
      } as any,
    ],
  })

  // 节点单击：通知父组件打开抽屉
  graph.on('node:click', (evt: any) => {
    const id = evt.target?.id as string | undefined
    if (!id) return
    const node = props.nodes.find((n) => n.id === id)
    if (node) emit('node-click', node)
  })

  // 节点双击：以此节点展开
  graph.on('node:dblclick', (evt: any) => {
    const id = evt.target?.id as string | undefined
    if (id) emit('node-dblclick', id)
  })

  // 边点击
  graph.on('edge:click', (evt: any) => {
    const id = evt.target?.id as string | undefined
    if (!id) return
    const edgeData = graph.getEdgeData(id)
    const edge = props.edges.find(
      (e) => e.source === edgeData?.source && e.target === edgeData?.target
    )
    if (edge) emit('edge-click', edge)
  })

  graphRef.value = graph
  graph.render().catch((e) => console.error('G6 render failed:', e))
}

// ---- 数据更新 ----
const updateData = async () => {
  const graph = graphRef.value
  if (!graph) return
  graph.setData(toGraphData())
  try {
    await graph.render()
  } catch (e) {
    console.error('G6 update failed:', e)
  }
}

watch(
  () => [props.nodes, props.edges],
  () => nextTick(() => updateData()),
  { deep: true }
)

// ---- 布局切换：重建图实例 ----
watch(
  () => props.layout,
  () => {
    destroyGraph()
    nextTick(() => initGraph())
  }
)

// ---- 工具栏操作 ----
const zoomBy = (factor: number) => {
  const graph = graphRef.value
  if (!graph) return
  const cur = graph.getZoom?.() ?? 1
  graph.zoomTo(Math.min(Math.max(cur * factor, 0.2), 4)).catch(() => {})
}

const fitView = () => {
  graphRef.value?.fitView({ when: 'always' }).catch(() => {})
}

const fitCenter = () => {
  graphRef.value?.fitCenter().catch(() => {})
}

// ---- 暴露给父组件 ----
const focusNode = async (nodeId: string) => {
  const graph = graphRef.value
  if (!graph) return
  if (graph.hasNode(nodeId)) {
    clearSelected()
    graph.setElementState(nodeId, 'selected')
    await graph.focusElement(nodeId).catch(() => {})
  } else {
    emit('node-dblclick', nodeId)
  }
}

const highlightNode = (nodeId: string) => {
  const graph = graphRef.value
  if (!graph || !graph.hasNode(nodeId)) return
  clearSelected()
  graph.setElementState(nodeId, 'selected')
}

const clearSelected = () => {
  const graph = graphRef.value
  if (!graph) return
  try {
    graph.getNodeData().forEach((n) => {
      if (graph.getElementState(n.id).includes('selected')) {
        graph.setElementState(n.id, [])
      }
    })
  } catch {
    // ignore
  }
}

defineExpose({ focusNode, highlightNode, clearSelected })

// ---- 生命周期 ----
const handleResize = () => {
  const graph = graphRef.value
  const container = containerRef.value
  if (!graph || !container) return
  graph.setSize(container.clientWidth, container.clientHeight)
}

const destroyGraph = () => {
  graphRef.value?.destroy()
  graphRef.value = null
}

onMounted(() => {
  initGraph()
  resizeObserver = new ResizeObserver(() => handleResize())
  if (containerRef.value) resizeObserver.observe(containerRef.value)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  destroyGraph()
})
</script>

<style scoped>
.canvas-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 600px;
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgb(var(--v-theme-surface));
  border-radius: 8px 8px 0 0;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  flex-wrap: wrap;
  gap: 8px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.graph-container {
  position: relative;
  flex: 1;
  width: 100%;
  min-height: 520px;
  background: rgb(var(--v-theme-surface-variant));
  border-radius: 0 0 8px 8px;
  overflow: hidden;
}

.overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgb(var(--v-theme-surface));
  opacity: 0.92;
  z-index: 10;
}

:deep(.l3-minimap) {
  border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  background: rgba(255, 255, 255, 0.9);
}
</style>
