<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { streamSubtitles } from '../summaryApi.js'

const props = defineProps({
  url: { type: String, default: '' },
})

const busy = ref(false)
const status = ref('')
const error = ref('')
const stats = ref(null)
const segments = ref([])
const exports = ref(null)
const copied = ref('')
const downloaded = ref('')
let controller = null
let attempt = 0

const ready = computed(() => Boolean(props.url.trim()))

const formats = [
  { key: 'plain', label: 'TXT', ext: 'txt', type: 'text/plain;charset=utf-8' },
  { key: 'timed', label: '时间戳 TXT', ext: 'txt', type: 'text/plain;charset=utf-8' },
  { key: 'srt', label: 'SRT', ext: 'srt', type: 'application/x-subrip;charset=utf-8' },
  { key: 'vtt', label: 'VTT', ext: 'vtt', type: 'text/vtt;charset=utf-8' },
]

onUnmounted(() => controller?.abort())

function clock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const minutes = Math.floor(total / 60)
  const secs = total % 60
  return `${minutes}:${String(secs).padStart(2, '0')}`
}

function fileStamp() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
}

function downloadFormat(item) {
  const content = exports.value?.[item.key]
  if (!content) return
  const url = URL.createObjectURL(new Blob([content], { type: item.type }))
  const link = document.createElement('a')
  link.href = url
  link.download = `字幕-${fileStamp()}.${item.ext}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
  downloaded.value = item.key
  setTimeout(() => {
    if (downloaded.value === item.key) downloaded.value = ''
  }, 1500)
}

async function onProcess() {
  if (busy.value) return
  const target = props.url.trim()
  if (!target) {
    error.value = '请先在上方粘贴视频链接'
    return
  }
  controller?.abort()
  controller = new AbortController()
  const current = ++attempt
  segments.value = []
  stats.value = null
  exports.value = null
  copied.value = ''
  error.value = ''
  status.value = '正在解析字幕'
  busy.value = true
  try {
    await streamSubtitles(
      { url: target },
      (block) => {
        const data = block.data || {}
        if (block.event === 'status') {
          status.value = data.message || ''
        } else if (block.event === 'stats') {
          stats.value = data
        } else if (block.event === 'segment') {
          segments.value.push(data)
        } else if (block.event === 'done') {
          const result = data.result || {}
          stats.value = result.stats || stats.value
          segments.value = result.segments || segments.value
          exports.value = result.exports || null
        } else if (block.event === 'error') {
          throw new Error(data.message || '字幕处理失败，请重试')
        }
      },
      controller.signal,
    )
    if (current === attempt) status.value = ''
  } catch (err) {
    if (current !== attempt) return
    if (err.name === 'AbortError') return
    error.value = err.message || '字幕处理失败，请重试'
  } finally {
    if (current === attempt) {
      busy.value = false
      controller = null
    }
  }
}

async function copyFormat(key) {
  if (!exports.value?.[key]) return
  try {
    await navigator.clipboard.writeText(exports.value[key])
    copied.value = key
  } catch {
    copied.value = ''
    error.value = '复制没有完成，请重试'
  }
}
</script>

<template>
  <article class="surface p-4 sm:p-6" aria-live="polite">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="flex items-center gap-2 text-xs text-stone">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="busy ? 'animate-pulse bg-copper' : 'bg-copper/60'"></span>
        {{ busy ? status || '正在处理' : stats ? '字幕解析完成' : '抓取字幕，自动清洗、断句与分段' }}
      </p>
      <span v-if="stats" class="text-xs tabular-nums text-stone">共 {{ segments.length }} 段</span>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" class="btn-primary" :disabled="busy || !ready" @click="onProcess">
        {{ busy ? '正在解析' : '解析字幕' }}
      </button>
    </div>

    <p v-if="!ready && !busy" class="mt-3 text-xs text-stone">先在上方粘贴视频链接，再点击解析字幕。</p>

    <p v-if="error" class="mt-3 rounded-xl border border-white/70 bg-white/50 px-3.5 py-2.5 text-sm text-copper-deep">
      {{ error }}
    </p>

    <div v-if="stats" class="mt-4 flex flex-wrap gap-2">
      <span class="stat-pill">{{ stats.cues }} 条字幕</span>
      <span class="stat-pill">{{ stats.segments }} 个分段</span>
      <span class="stat-pill">{{ stats.sentences }} 句</span>
      <span class="stat-pill">{{ stats.characters }} 字</span>
      <span v-if="stats.duration" class="stat-pill tabular-nums">时长 {{ clock(stats.duration) }}</span>
    </div>

    <p v-if="stats && stats.truncated" class="mt-2 text-sm text-stone">字幕较长，只处理了前一部分。</p>

    <div v-if="segments.length" class="mt-6">
      <div class="flex items-center justify-between gap-2 border-t border-line pt-4">
        <h3 class="result-title">语义分段</h3>
        <span class="text-xs tabular-nums text-stone">共 {{ segments.length }} 段</span>
      </div>
      <ol class="surface-inset mt-3 max-h-96 divide-y divide-line overflow-auto">
        <li v-for="item in segments" :key="item.index" class="px-3.5 py-3">
          <p class="text-xs tabular-nums text-stone">第 {{ item.index + 1 }} 段 · {{ clock(item.start) }} – {{ clock(item.end) }}</p>
          <p class="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-ink">{{ item.text }}</p>
        </li>
      </ol>
    </div>

    <div v-if="exports" class="mt-4 space-y-2.5 border-t border-line pt-4">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-stone">下载</span>
        <button
          v-for="item in formats"
          :key="`download-${item.key}`"
          type="button"
          class="chip"
          @click="downloadFormat(item)"
        >
          {{ downloaded === item.key ? '已开始下载' : `${item.label} 文件` }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-stone">复制</span>
        <button
          v-for="item in formats"
          :key="`copy-${item.key}`"
          type="button"
          class="btn-quiet"
          @click="copyFormat(item.key)"
        >
          {{ copied === item.key ? '已复制' : `复制 ${item.label}` }}
        </button>
      </div>
    </div>

    <div v-if="!busy && !stats && !error" class="empty-state mt-4">
      点击解析字幕，统计与语义分段会显示在这里
    </div>
  </article>
</template>
