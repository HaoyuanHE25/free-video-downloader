<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fileUrl } from '../api.js'
import { formatBytes, formatDuration } from '../format.js'
import { renderMessage } from '../i18n/messages.js'

const { t } = useI18n()

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
  if (props.job && props.job.status === 'queued') return t('result.queued')
  if (!props.job || !props.job.progress) return t('result.saving')
  return t('result.savingPercent', { percent: percent.value })
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
  <section class="mx-auto mt-2 w-full" aria-live="polite">
    <article class="ink-band rounded-[18px] p-4 sm:p-5">
      <p v-if="parsing" class="text-sm text-cream/55">{{ t('result.loading') }}</p>

      <p v-else-if="error && !meta" class="rounded-xl border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-[#f3c8c2]">
        {{ renderMessage(error) }}
      </p>

      <template v-else-if="meta">
        <div class="flex items-start gap-3">
          <img
            v-if="meta.thumbnail && !coverBroken"
            :src="meta.thumbnail"
            :alt="meta.title"
            class="aspect-video w-20 shrink-0 rounded-[12px] border border-white/12 object-cover sm:w-32"
            @error="coverBroken = true"
          />
          <div class="min-w-0 flex-1">
            <p class="text-[11px] leading-4 text-cream/50">
              {{ renderMessage(meta.platform) }}<span v-if="duration"> · {{ duration }}</span>
            </p>
            <h2 class="mt-0.5 line-clamp-2 text-sm font-bold leading-snug text-cream sm:text-base">
              {{ meta.title }}
            </h2>

            <div class="mt-2 flex flex-wrap items-center gap-1.5" role="radiogroup" :aria-label="t('result.qualityLabel')">
              <button
                v-for="item in meta.formats"
                :key="item.format_id"
                type="button"
                role="radio"
                class="inline-flex min-h-8 cursor-pointer items-center rounded-full border px-2.5 text-xs transition-all duration-150"
                :class="item.format_id === selectedId ? 'border-copper bg-copper/15 font-medium text-white shadow-[0_0_0_1px_rgba(79,109,168,0.4)]' : 'border-white/10 bg-white/[0.04] text-cream/80 hover:border-copper/60 hover:bg-white/[0.08] hover:text-cream'"
                :aria-checked="item.format_id === selectedId"
                :disabled="phase === 'saving'"
                @click="emit('select', item.format_id)"
              >
                {{ renderMessage(item.label) }}
                <span class="ml-1 text-cream/45">{{ formatBytes(item.filesize) }}</span>
              </button>

              <a
                v-if="phase === 'done' && job"
                ref="link"
                :href="fileHref"
                class="mt-0 inline-flex min-h-9 w-full shrink-0 items-center justify-center rounded-full border border-white/20 bg-copper px-4 text-xs font-medium text-cream shadow-[inset_0_1px_0_rgba(255,255,255,0.22),0_10px_24px_-12px_rgba(63,90,140,0.7)] transition-all duration-150 hover:-translate-y-px hover:bg-copper-deep hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_12px_26px_-12px_rgba(63,90,140,0.8)] active:translate-y-0 active:scale-[0.98] sm:ml-auto sm:min-h-8 sm:w-auto"
                @click="onAgain"
              >
                {{ t('result.downloadAgain') }}
              </a>
              <button
                v-else
                type="button"
                class="mt-0 inline-flex min-h-9 w-full shrink-0 items-center justify-center rounded-full border border-white/20 bg-copper px-4 text-xs font-medium text-cream shadow-[inset_0_1px_0_rgba(255,255,255,0.22),0_10px_24px_-12px_rgba(63,90,140,0.7)] transition-all duration-150 hover:-translate-y-px hover:bg-copper-deep hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_12px_26px_-12px_rgba(63,90,140,0.8)] active:translate-y-0 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 sm:ml-auto sm:min-h-8 sm:w-auto"
                :disabled="phase === 'saving' || !selectedId"
                @click="emit('save')"
              >
                {{ phase === 'saving' ? t('result.saving') : phase === 'failed' ? t('result.retry') : t('result.save') }}
              </button>
            </div>
          </div>
        </div>

        <p v-if="meta.hint" class="mt-2 line-clamp-1 text-xs text-cream/45">{{ renderMessage(meta.hint) }}</p>

        <div v-if="phase === 'saving'" class="mt-2 flex items-center gap-2">
          <div
            class="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            :aria-valuenow="percent"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-label="savingLabel"
          >
            <div class="h-full bg-copper transition-all duration-200" :style="{ width: `${Math.max(percent, 8)}%` }"></div>
          </div>
          <span class="shrink-0 text-xs tabular-nums text-cream/55">{{ savingLabel }}</span>
        </div>

        <p v-if="phase === 'failed' && error" class="mt-2 text-xs text-[#f3c8c2]">{{ renderMessage(error) }}</p>
        <p v-else-if="phase === 'done'" class="mt-2 text-xs text-cream/55">{{ t('result.doneNote') }}</p>
      </template>
    </article>
  </section>
</template>
