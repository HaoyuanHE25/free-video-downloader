<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { renderMessage, stageMessage } from '../i18n/messages.js'
import { streamSummary } from '../summaryApi.js'
import MarkdownView from './MarkdownView.vue'

const props = defineProps({
  url: { type: String, default: '' },
})

const { t } = useI18n()

const phase = ref('idle')
const status = ref('')
const error = ref('')
const outline = ref('')
const points = ref([])
const chapters = ref([])
const result = ref(null)
const copied = ref(false)
let controller = null
let attempt = 0

const ready = computed(() => Boolean(props.url.trim()))
const busy = computed(() => ['fetching', 'processing', 'summarizing', 'building'].includes(phase.value))
const hasContent = computed(() => Boolean(outline.value) || points.value.length > 0)

onUnmounted(() => controller?.abort())

function reset() {
  status.value = ''
  error.value = ''
  outline.value = ''
  points.value = []
  chapters.value = []
  result.value = null
  copied.value = false
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const body = `${minutes}:${String(secs).padStart(2, '0')}`
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}` : body
}

function onEvent(block) {
  const data = block.data || {}
  if (block.event === 'status') {
    phase.value = {
      fetching_subtitles: 'fetching',
      processing_subtitles: 'processing',
      summarizing: 'summarizing',
      building_mindmap: 'building',
    }[data.stage] || phase.value
    status.value = stageMessage(data.stage, data.message)
    return
  }
  if (block.event === 'delta') {
    if (data.target === 'outline') {
      phase.value = 'summarizing'
      outline.value += data.text || ''
    }
    return
  }
  if (block.event === 'outline') {
    outline.value = data.text || ''
    return
  }
  if (block.event === 'point') {
    points.value[data.index] = data.text
    return
  }
  if (block.event === 'chapter') {
    chapters.value[data.index] = { title: data.title, start: data.start, summary: data.summary }
    return
  }
  if (block.event === 'done') {
    const payload = data.result || {}
    result.value = payload
    outline.value = payload.outline || outline.value
    points.value = payload.points || points.value
    chapters.value = payload.chapters || chapters.value
    phase.value = 'done'
    status.value = ''
    return
  }
  if (block.event === 'error') {
    throw new Error(data.message || 'error.summaryFailed')
  }
}

async function onSummarize() {
  if (busy.value) return
  const target = props.url.trim()
  if (!target) {
    error.value = 'error.needUrl'
    return
  }
  controller?.abort()
  controller = new AbortController()
  const current = ++attempt
  reset()
  phase.value = 'fetching'
  status.value = 'stage.connecting'
  try {
    await streamSummary(target, onEvent, controller.signal)
    if (current !== attempt) return
    if (phase.value !== 'done') throw new Error('error.summaryInterrupted')
  } catch (err) {
    if (current !== attempt) return
    if (err.name === 'AbortError') {
      if (phase.value !== 'done') {
        phase.value = 'idle'
        status.value = ''
      }
      return
    }
    phase.value = 'failed'
    status.value = ''
    error.value = err.message || 'error.summaryFailed'
  } finally {
    if (current === attempt) controller = null
  }
}

async function onCopy() {
  if (!hasContent.value) return
  const text = [
    outline.value,
    ...points.value.filter(Boolean).map((item) => `- ${item}`),
    chapters.value
      .filter(Boolean)
      .map((item) => `${clock(item.start)} ${item.title}\n${item.summary}`)
      .join('\n\n'),
  ]
    .filter(Boolean)
    .join('\n\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
  } catch {
    copied.value = false
    error.value = 'common.copyFailed'
  }
}
</script>

<template>
  <article class="surface p-4 sm:p-6" aria-live="polite">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="flex items-center gap-2 text-xs text-stone">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="busy ? 'animate-pulse bg-copper' : 'bg-copper/60'"></span>
        {{ busy ? renderMessage(status) || t('summary.busy') : phase === 'done' ? t('summary.done') : t('summary.idle') }}
      </p>
      <button v-if="hasContent" type="button" class="btn-quiet" @click="onCopy">
        {{ copied ? t('summary.copied') : t('summary.copy') }}
      </button>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" class="btn-primary" :disabled="busy || !ready" @click="onSummarize">
        {{ busy ? t('summary.actionBusy') : phase === 'done' ? t('summary.actionAgain') : t('summary.action') }}
      </button>
    </div>

    <p v-if="!ready && !busy" class="mt-3 text-xs text-stone">{{ t('summary.emptyReady') }}</p>

    <p v-if="error" class="mt-3 rounded-xl border border-white/70 bg-white/50 px-3.5 py-2.5 text-sm text-copper-deep">
      {{ renderMessage(error) }}
    </p>

    <div v-if="busy && outline" class="surface-inset mt-4 p-3.5">
      <MarkdownView :text="outline" />
      <span class="animate-pulse text-copper">▍</span>
    </div>

    <template v-if="hasContent">
      <p v-if="result && result.truncated" class="mt-4 text-sm text-stone">{{ t('summary.truncated') }}</p>
      <h3 class="result-title mt-6">{{ t('summary.outline') }}</h3>
      <div class="surface-inset mt-2.5 px-4 py-3.5">
        <MarkdownView :text="outline" />
      </div>
      <h3 v-if="points.length" class="result-title mt-6">{{ t('summary.points') }}</h3>
      <ul v-if="points.length" class="mt-3 space-y-2">
        <li v-for="(item, index) in points" :key="index" class="flex items-start gap-2.5 text-sm leading-6 text-ink">
          <span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-copper"></span>
          <MarkdownView class="min-w-0 break-words" :text="item" inline />
        </li>
      </ul>
      <h3 v-if="chapters.length" class="result-title mt-6">{{ t('summary.chapters') }}</h3>
      <ol v-if="chapters.length" class="mt-3 space-y-3">
        <li v-for="(item, index) in chapters" :key="index" class="surface-inset p-3.5">
          <p class="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
            <span class="rounded-full bg-white/60 px-2 py-0.5 text-xs tabular-nums text-copper-deep">{{ clock(item.start) }}</span>
            {{ item.title }}
          </p>
          <MarkdownView class="mt-1.5 text-stone" :text="item.summary" />
        </li>
      </ol>
    </template>

    <div v-if="!busy && !error && !hasContent" class="empty-state mt-4">
      {{ t('summary.empty') }}
    </div>
  </article>
</template>
