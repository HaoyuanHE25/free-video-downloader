<script setup>
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { streamMindmap } from '../summaryApi.js'

const props = defineProps({
  url: { type: String, default: '' },
})

const busy = ref(false)
const status = ref('')
const error = ref('')
const tree = ref(null)
const copied = ref(false)
const expanded = ref(false)
const exporting = ref(false)
const exportScale = ref(2)
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const dragging = ref(false)
const svgRef = ref(null)
const stageRef = ref(null)
let controller = null
let dragStart = null

const ready = computed(() => Boolean(props.url.trim()))
const canRun = computed(() => !busy.value && ready.value)
const zoomPercent = computed(() => Math.round(zoom.value * 100))

const COLORS = ['#4f6da8', '#6f93b8', '#6f9e85', '#8f86b8', '#b98fa3', '#a89573', '#8492b3', '#5f9e9a']
const FONT_STACK = '"PingFang SC", "Microsoft YaHei", sans-serif'
const NODE_H = 26
const ROW_GAP = 6
const LEVEL_GAP = 52
const DOT_GAP = 10
const DOT_R = 3
const PAD_X = 22
const PAD_Y = 20
const MIN_ZOOM = 0.2
const MAX_ZOOM = 4

let canvasContext = null

function cleanLabel(value, limit = 52) {
  const text = String(value || '').replace(/\s+/g, ' ').trim() || '未命名'
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

function nodeStyle(depth) {
  if (depth === 0) return { size: 14, weight: 700, fill: '#4b5263' }
  if (depth === 1) return { size: 13.5, weight: 600, fill: '#4b5263' }
  if (depth === 2) return { size: 13, weight: 600, fill: '#4b5263' }
  return { size: 12.5, weight: 500, fill: '#3f4552' }
}

function measureText(text, style) {
  if (!canvasContext) {
    canvasContext = document.createElement('canvas').getContext('2d')
  }
  canvasContext.font = `${style.weight} ${style.size}px ${FONT_STACK}`
  return canvasContext.measureText(text).width
}

function curvePath(x1, y1, x2, y2) {
  const dx = Math.max(18, (x2 - x1) * 0.5)
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
}

const layout = computed(() => {
  if (!tree.value) return null
  const nodes = []
  const levels = []

  const build = (node, depth) => {
    const label = cleanLabel(node.label)
    const style = nodeStyle(depth)
    const item = {
      id: nodes.length + 1,
      label,
      depth,
      width: measureText(label, style),
      size: style.size,
      weight: style.weight,
      fill: style.fill,
      hasChildren: (node.children || []).length > 0,
      children: [],
    }
    nodes.push(item)
    ;(levels[depth] || (levels[depth] = [])).push(item)
    for (const child of node.children || []) {
      item.children.push(build(child, depth + 1))
    }
    return item
  }

  const root = build(tree.value, 0)

  const columns = levels.map((list) => Math.max(...list.map((item) => item.width)) + DOT_GAP + DOT_R * 2)
  const columnX = []
  let cursor = PAD_X
  for (let depth = 0; depth < columns.length; depth += 1) {
    columnX[depth] = cursor
    cursor += columns[depth] + LEVEL_GAP
  }

  const measureHeight = (node) => {
    if (!node.children.length) {
      node.height = NODE_H
      return node.height
    }
    let total = 0
    node.children.forEach((child, index) => {
      total += measureHeight(child)
      if (index) total += ROW_GAP
    })
    node.height = Math.max(NODE_H, total)
    return node.height
  }
  measureHeight(root)

  const childrenHeight = (node) =>
    node.children.reduce((sum, child, index) => sum + child.height + (index ? ROW_GAP : 0), 0)

  const place = (node, top) => {
    node.x = columnX[node.depth]
    node.y = top + node.height / 2
    node.dotX = node.x + node.width + DOT_GAP
    let childTop = top + (node.height - childrenHeight(node)) / 2
    node.children.forEach((child) => {
      place(child, childTop)
      childTop += child.height + ROW_GAP
    })
  }
  place(root, PAD_Y)

  const paint = (node, colorIndex) => {
    node.color = COLORS[colorIndex % COLORS.length]
    node.children.forEach((child, index) => paint(child, colorIndex + 1 + index))
  }
  root.color = '#4f6da8'
  root.children.forEach((child, index) => paint(child, index))

  for (const node of nodes) {
    if (node.depth > 0 && node.hasChildren) node.fill = node.color
  }

  const edges = []
  for (const node of nodes) {
    for (const child of node.children) {
      edges.push({ color: child.color, d: curvePath(node.dotX, node.y, child.x - 9, child.y) })
    }
  }

  return {
    nodes,
    edges,
    width: Math.ceil(Math.max(...nodes.map((node) => node.dotX)) + DOT_R + PAD_X),
    height: Math.ceil(root.height + PAD_Y * 2),
  }
})

function reset() {
  tree.value = null
  copied.value = false
}

async function onGenerate() {
  if (busy.value) return
  const target = props.url.trim()
  if (!target) {
    error.value = '请先在上方粘贴视频链接'
    return
  }
  controller?.abort()
  controller = new AbortController()
  error.value = ''
  status.value = '正在生成导图'
  busy.value = true
  reset()
  try {
    await streamMindmap(
      { url: target },
      (block) => {
        const data = block.data || {}
        if (block.event === 'status') {
          status.value = data.message || ''
        } else if (block.event === 'tree') {
          tree.value = data.root
        } else if (block.event === 'done') {
          const result = data.result || {}
          if (result.root) tree.value = result.root
        } else if (block.event === 'error') {
          throw new Error(data.message || '思维导图生成失败，请重试')
        }
      },
      controller.signal,
    )
  } catch (err) {
    if (err.name === 'AbortError') return
    error.value = err.message || '思维导图生成失败，请重试'
  } finally {
    busy.value = false
    status.value = ''
    controller = null
  }
}

function plainSource(node = tree.value) {
  if (!node) return ''
  const lines = []
  const walk = (item, depth) => {
    lines.push(`${'  '.repeat(depth)}- ${cleanLabel(item.label, 120)}`)
    for (const child of item.children || []) walk(child, depth + 1)
  }
  walk(node, 0)
  return lines.join('\n')
}

async function copySource() {
  if (!tree.value) return
  try {
    await navigator.clipboard.writeText(plainSource())
    copied.value = true
  } catch {
    copied.value = false
    error.value = '复制没有完成，请重试'
  }
}

function clampZoom(value) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))))
}

function zoomBy(delta) {
  zoom.value = clampZoom(zoom.value + delta)
}

function resetPan() {
  panX.value = 0
  panY.value = 0
}

function fitToScreen() {
  if (!layout.value || !stageRef.value) return
  const rect = stageRef.value.getBoundingClientRect()
  const width = Math.max(rect.width - 48, 160)
  const height = Math.max(rect.height - 48, 120)
  const scale = Math.min(width / layout.value.width, height / layout.value.height, 2)
  zoom.value = clampZoom(scale)
  resetPan()
}

function openFullscreen() {
  if (!layout.value) return
  expanded.value = true
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKeydown)
  nextTick(fitToScreen)
}

function closeFullscreen() {
  expanded.value = false
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKeydown)
  resetPan()
  zoom.value = 1
}

function onKeydown(event) {
  if (event.key === 'Escape') closeFullscreen()
}

function startDrag(event) {
  if (event.button !== 0) return
  dragging.value = true
  dragStart = { x: event.clientX, y: event.clientY, panX: panX.value, panY: panY.value }
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function onDrag(event) {
  if (!dragging.value || !dragStart) return
  panX.value = dragStart.panX + (event.clientX - dragStart.x)
  panY.value = dragStart.panY + (event.clientY - dragStart.y)
}

function endDrag(event) {
  dragging.value = false
  dragStart = null
  event.currentTarget.releasePointerCapture?.(event.pointerId)
}

function onWheel(event) {
  zoomBy(event.deltaY > 0 ? -0.15 : 0.15)
}

function fileStamp() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
}

function fileBase() {
  const label = cleanLabel(tree.value?.label, 24).replace(/[\\/:*?"<>|\s]+/g, '-')
  return `思维导图-${label || '未命名'}-${fileStamp()}`
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

function serializeSvg() {
  if (!svgRef.value || !layout.value) return ''
  const clone = svgRef.value.cloneNode(true)
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(layout.value.width))
  clone.setAttribute('height', String(layout.value.height))
  clone.querySelectorAll('text').forEach((text) => {
    const classes = text.getAttribute('class') || ''
    if (classes.includes('mmd-leaf')) {
      text.setAttribute('text-decoration', 'underline')
      text.setAttribute('text-decoration-color', '#a9b8d6')
    } else if (classes.includes('mmd-root')) {
      text.setAttribute('text-decoration', 'underline')
      text.setAttribute('text-decoration-color', '#4f6da8')
    }
    text.removeAttribute('class')
  })
  return new XMLSerializer().serializeToString(clone)
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片加载失败'))
    image.src = url
  })
}

async function downloadPng() {
  if (exporting.value) return
  const source = serializeSvg()
  if (!source || !layout.value) return
  const maxSide = 8192
  const scale = Math.min(exportScale.value, maxSide / Math.max(layout.value.width, layout.value.height))
  exporting.value = true
  error.value = ''
  const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const image = await loadImage(url)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(layout.value.width * scale))
    canvas.height = Math.max(1, Math.round(layout.value.height * scale))
    const context = canvas.getContext('2d')
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('图片导出失败')
    saveBlob(blob, `${fileBase()}.png`)
  } catch {
    error.value = '图片导出失败，请重试'
  } finally {
    URL.revokeObjectURL(url)
    exporting.value = false
  }
}

function downloadSvg() {
  const source = serializeSvg()
  if (!source) return
  saveBlob(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }), `${fileBase()}.svg`)
}

onUnmounted(() => {
  controller?.abort()
  if (expanded.value) closeFullscreen()
})
</script>

<template>
  <article class="surface p-4 sm:p-6" aria-live="polite">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="flex items-center gap-2 text-xs text-stone">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="busy ? 'animate-pulse bg-copper' : 'bg-copper/60'"></span>
        {{ busy ? status || '正在处理' : tree ? '导图已生成' : '根据链接生成结构清晰的思维导图' }}
      </p>
      <div v-if="tree" class="flex flex-wrap items-center gap-1">
        <button type="button" class="btn-quiet" @click="openFullscreen">全屏</button>
        <button type="button" class="btn-quiet" :disabled="exporting" @click="downloadPng">
          {{ exporting ? '导出中' : '下载 PNG' }}
        </button>
        <button type="button" class="btn-quiet" @click="downloadSvg">下载 SVG</button>
        <button type="button" class="btn-quiet" @click="copySource">
          {{ copied ? '已复制' : '复制大纲' }}
        </button>
      </div>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" class="btn-primary" :disabled="!canRun" @click="onGenerate">
        {{ busy ? '正在生成' : tree ? '重新生成' : '生成导图' }}
      </button>
    </div>

    <p v-if="!ready && !busy" class="mt-3 text-xs text-stone">先在上方粘贴视频链接，再点击生成导图。</p>

    <p v-if="error" class="mt-3 rounded-xl border border-white/70 bg-white/50 px-3.5 py-2.5 text-sm text-copper-deep">
      {{ error }}
    </p>

    <div v-if="layout" class="mindmap-view mt-4 overflow-auto rounded-[16px] border border-white/70 bg-white/55 p-2.5 backdrop-blur-md">
      <svg
        ref="svgRef"
        :viewBox="`0 0 ${layout.width} ${layout.height}`"
        :style="{ width: `${layout.width}px`, height: `${layout.height}px`, fontFamily: FONT_STACK }"
        class="block"
        role="img"
        aria-label="视频思维导图"
      >
        <rect :width="layout.width" :height="layout.height" fill="#ffffff" />
        <path
          v-for="(edge, index) in layout.edges"
          :key="`e-${index}`"
          :d="edge.d"
          :stroke="edge.color"
          stroke-width="1.6"
          fill="none"
          stroke-linecap="round"
        />
        <g v-for="node in layout.nodes" :key="`n-${node.id}`">
          <circle
            v-if="node.hasChildren"
            :cx="node.dotX"
            :cy="node.y"
            :r="node.depth === 0 ? 4.4 : 4"
            fill="#ffffff"
            :stroke="node.color"
            stroke-width="1.6"
          />
          <text
            :x="node.x"
            :y="node.y"
            dominant-baseline="middle"
            :font-size="node.size"
            :font-weight="node.weight"
            :fill="node.fill"
            :class="{ 'mmd-leaf': !node.hasChildren && node.depth > 0, 'mmd-root': node.depth === 0 }"
          >
            {{ node.label }}
          </text>
        </g>
      </svg>
    </div>

    <div v-else-if="!busy && !error" class="empty-state mt-4">
      点击生成导图，结构图会显示在这里
    </div>

    <Teleport to="body">
      <div v-if="expanded && layout" class="mm-modal" role="dialog" aria-modal="true" aria-label="思维导图全屏">
        <header class="mm-bar">
          <div class="flex min-w-0 items-center gap-2">
            <span class="mm-title">思维导图</span>
            <span class="rounded-full bg-cream px-2 py-0.5 text-xs tabular-nums text-stone">{{ zoomPercent }}%</span>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-1.5">
            <button type="button" class="btn-quiet" @click="fitToScreen">适应屏幕</button>
            <button type="button" class="mm-icon" aria-label="缩小" @click="zoomBy(-0.15)">−</button>
            <button type="button" class="mm-icon" aria-label="放大" @click="zoomBy(0.15)">＋</button>
            <span class="mm-divider"></span>
            <select v-model.number="exportScale" class="mm-select" aria-label="PNG 清晰度">
              <option :value="2">PNG 2x</option>
              <option :value="3">PNG 3x</option>
            </select>
            <button type="button" class="btn-secondary" :disabled="exporting" @click="downloadPng">
              {{ exporting ? '导出中' : '下载 PNG' }}
            </button>
            <button type="button" class="btn-secondary" @click="downloadSvg">下载 SVG</button>
            <button type="button" class="mm-icon" aria-label="关闭全屏" @click="closeFullscreen">×</button>
          </div>
        </header>
        <div
          ref="stageRef"
          class="mm-stage"
          :class="{ 'mm-dragging': dragging }"
          @pointerdown="startDrag"
          @pointermove="onDrag"
          @pointerup="endDrag"
          @pointercancel="endDrag"
          @wheel.prevent="onWheel"
        >
          <div class="mm-canvas" :style="{ transform: `translate(${panX}px, ${panY}px) scale(${zoom})` }">
            <svg
              :viewBox="`0 0 ${layout.width} ${layout.height}`"
              :style="{ width: `${layout.width}px`, height: `${layout.height}px`, fontFamily: FONT_STACK }"
              class="block"
              role="img"
              aria-label="视频思维导图全屏"
            >
              <rect :width="layout.width" :height="layout.height" fill="#ffffff" />
              <path
                v-for="(edge, index) in layout.edges"
                :key="`fe-${index}`"
                :d="edge.d"
                :stroke="edge.color"
                stroke-width="1.6"
                fill="none"
                stroke-linecap="round"
              />
              <g v-for="node in layout.nodes" :key="`fn-${node.id}`">
                <circle
                  v-if="node.hasChildren"
                  :cx="node.dotX"
                  :cy="node.y"
                  :r="node.depth === 0 ? 4.4 : 4"
                  fill="#ffffff"
                  :stroke="node.color"
                  stroke-width="1.6"
                />
                <text
                  :x="node.x"
                  :y="node.y"
                  dominant-baseline="middle"
                  :font-size="node.size"
                  :font-weight="node.weight"
                  :fill="node.fill"
                  :class="{ 'mmd-leaf': !node.hasChildren && node.depth > 0, 'mmd-root': node.depth === 0 }"
                >
                  {{ node.label }}
                </text>
              </g>
            </svg>
          </div>
        </div>
        <p class="mm-hint">拖动查看 · 滚轮缩放 · Esc 关闭</p>
      </div>
    </Teleport>
  </article>
</template>

<style scoped>
.mindmap-view {
  border: 1px solid rgba(255, 255, 255, 0.7);
  background: rgba(255, 255, 255, 0.55);
  max-height: 62vh;
  min-height: 360px;
}

.mindmap-view svg {
  margin: auto;
  min-width: 100%;
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
}

.mmd-leaf {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  text-decoration-color: #a9b8d6;
}

.mmd-root {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 4px;
  text-decoration-color: #4f6da8;
}

.mm-modal {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  background: rgba(238, 241, 247, 0.9);
  backdrop-filter: blur(28px) saturate(160%);
  -webkit-backdrop-filter: blur(28px) saturate(160%);
}

.mm-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.6);
  padding: 0.65rem 1rem;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}

.mm-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1b1f2a;
}

.mm-icon {
  display: inline-flex;
  height: 2rem;
  width: 2rem;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.5);
  color: #5b6272;
  font-size: 0.95rem;
  line-height: 1;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}

.mm-icon:hover {
  border-color: rgba(79, 109, 168, 0.4);
  background: rgba(255, 255, 255, 0.75);
  color: #3c5484;
}

.mm-divider {
  height: 1px;
  width: 1px;
  background: rgba(91, 98, 114, 0.2);
}

.mm-select {
  min-height: 2rem;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.5);
  padding: 0 0.6rem;
  color: #5b6272;
  font-size: 0.75rem;
  outline: none;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.mm-select:focus {
  border-color: rgba(79, 109, 168, 0.45);
}

.mm-stage {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.mm-stage.mm-dragging {
  cursor: grabbing;
}

.mm-canvas {
  display: flex;
  height: 100%;
  width: 100%;
  align-items: center;
  justify-content: center;
  transform-origin: center center;
  will-change: transform;
}

.mm-canvas > svg {
  flex: 0 0 auto;
}

.mm-hint {
  border-top: 1px solid rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.5);
  padding: 0.45rem 1rem;
  text-align: center;
  font-size: 0.6875rem;
  color: #5b6272;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

@media (max-width: 640px) {
  .mindmap-view {
    min-height: 300px;
    max-height: 52vh;
  }

  .mm-bar {
    padding: 0.5rem 0.75rem;
  }
}
</style>
