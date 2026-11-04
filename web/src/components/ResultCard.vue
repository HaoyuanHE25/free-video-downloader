<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { fileUrl } from '../api.js'
import { formatBytes, formatDuration } from '../format.js'

const props = defineProps({
  parsing: { type: Boolean, default: false },
  error: { type: String, default: '' },
  meta: { type: Object, default: null },
  selectedId: { type: String, default: '' },
  job: { type: Object, default: null },
  phase: { type: String, default: 'idle' },
})
const emit = defineEmits(['select', 'save'])

const link = ref(null)
const coverBroken = ref(false)
const autoStarted = new Set()

const percent = computed(() => Math.round((((props.job && props.job.progress) || 0) * 100)))
const fileHref = computed(() => (props.job ? fileUrl(props.job.id) : '#'))
const duration = computed(() => formatDuration(props.meta && props.meta.duration))
const savingLabel = computed(() => {
  if (props.job && props.job.status === 'queued') return '排队中'
  if (!props.job || !props.job.progress) return '正在保存'
  return `正在保存 ${percent.value}%`
})

watch(
  () => props.meta && props.meta.thumbnail,
  () => {
    coverBroken.value = false
  },
)

watch(
  () => (props.job ? `${props.job.id}:${props.job.status}` : ''),
  async (token) => {
    if (!token.endsWith(':finished') || !props.job) return
    if (autoStarted.has(props.job.id)) return
    autoStarted.add(props.job.id)
    await nextTick()
    link.value?.click()
  },
)

function onAgain(event) {
  if (event.isTrusted) {
    event.preventDefault()
    emit('save')
  }
}
</script>

<template>
  <section class="mx-auto mt-8 w-full max-w-3xl" aria-live="polite">
    <article class="rounded-xl border border-[rgba(28,25,23,0.06)] bg-card p-4 shadow-[0_12px_40px_rgba(120,72,32,0.08)] sm:p-5">
      <p v-if="parsing" class="text-sm text-stone">正在读取标题和清晰度…</p>

      <p v-else-if="error && !meta" class="text-base text-ink">{{ error }}</p>

      <template v-else-if="meta">
        <div class="flex flex-col gap-4 sm:flex-row">
          <img
            v-if="meta.thumbnail && !coverBroken"
            :src="meta.thumbnail"
            :alt="meta.title"
            class="aspect-video w-full rounded-lg object-cover sm:w-40"
            @error="coverBroken = true"
          />
          <div class="min-w-0">
            <p class="text-xs text-stone">{{ meta.platform }}</p>
            <h2 class="mt-1 break-words text-xl font-bold leading-snug text-ink">{{ meta.title }}</h2>
            <p v-if="duration" class="mt-1 text-sm text-stone">{{ duration }}</p>
          </div>
        </div>

        <p v-if="meta.hint" class="mt-4 text-sm text-stone">{{ meta.hint }}</p>

        <div class="mt-4 flex flex-wrap gap-2" role="radiogroup" aria-label="清晰度">
          <button
            v-for="item in meta.formats"
            :key="item.format_id"
            type="button"
            role="radio"
            class="min-h-11 cursor-pointer rounded-full border px-4 text-sm transition"
            :class="item.format_id === selectedId ? 'border-copper bg-white font-medium text-copper-deep' : 'border-line bg-cream text-ink hover:border-copper'"
            :aria-checked="item.format_id === selectedId"
            :disabled="phase === 'saving'"
            @click="emit('select', item.format_id)"
          >
            {{ item.label }}
            <span class="text-stone"> · {{ formatBytes(item.filesize) }}</span>
          </button>
        </div>

        <div v-if="phase === 'saving'" class="mt-4">
          <div
            class="h-2 overflow-hidden rounded-full bg-line"
            role="progressbar"
            :aria-valuenow="percent"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-label="savingLabel"
          >
            <div class="h-full bg-copper transition-all" :style="{ width: `${Math.max(percent, 8)}%` }"></div>
          </div>
          <p class="mt-2 text-sm text-stone">{{ savingLabel }}</p>
        </div>

        <p v-if="phase === 'failed' && error" class="mt-4 text-sm text-ink">{{ error }}</p>
        <p v-else-if="phase === 'done'" class="mt-4 text-sm text-stone">文件已交给浏览器。再存一份可以点「再次下载」。</p>

        <div class="mt-4">
          <a
            v-if="phase === 'done' && job"
            ref="link"
            :href="fileHref"
            class="inline-flex min-h-11 cursor-pointer items-center justify-center rounded-full bg-ink px-5 text-sm font-medium text-cream transition hover:bg-copper-deep"
            @click="onAgain"
          >
            再次下载
          </a>
          <button
            v-else
            type="button"
            class="inline-flex min-h-11 cursor-pointer items-center justify-center rounded-full bg-ink px-5 text-sm font-medium text-cream transition hover:bg-copper-deep disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="phase === 'saving' || !selectedId"
            @click="emit('save')"
          >
            {{ phase === 'saving' ? '正在保存' : phase === 'failed' ? '重试' : '保存到本地' }}
          </button>
        </div>
      </template>
    </article>
  </section>
</template>
