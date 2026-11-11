<script setup>
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getJob, getOrder, parseVideo, startDownload } from './api.js'
import { renderMessage } from './i18n/messages.js'
import { refreshSession } from './session.js'
import FeatureGrid from './components/FeatureGrid.vue'
import Highlights from './components/Highlights.vue'
import MemberGrid from './components/MemberGrid.vue'
import ParsePanel from './components/ParsePanel.vue'
import ResetPassword from './components/ResetPassword.vue'
import SiteFooter from './components/SiteFooter.vue'
import SiteHeader from './components/SiteHeader.vue'

const { t } = useI18n()

const WorkspaceView = defineAsyncComponent(() => import('./components/AiWorkspace.vue'))
const ResultCard = defineAsyncComponent(() => import('./components/ResultCard.vue'))

const url = ref('')
const started = ref(false)
const parsing = ref(false)
const parseError = ref('')
const meta = ref(null)
const selectedId = ref('')
const job = ref(null)
const phase = ref('idle')
const jobError = ref('')
let timer = 0
let attempt = 0

const workspaceVisible = computed(
  () => started.value && !parsing.value && Boolean(url.value.trim()),
)

const notice = ref('')
let noticeTimer = 0

// 从密码重置链接进入时，展示重置面板
const resetToken = ref('')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const checkout = params.get('checkout')
  const sessionId = params.get('session_id')
  resetToken.value = params.get('reset') || ''
  if (checkout) {
    window.history.replaceState({}, '', window.location.pathname + window.location.hash)
  }
  await refreshSession()
  if (checkout === 'success') await waitForPayment(sessionId)
  else if (checkout === 'cancel') showNotice('notice.checkoutCanceled')
})

function clearResetToken() {
  resetToken.value = ''
  window.history.replaceState({}, '', window.location.pathname + window.location.hash)
}

function onResetDone() {
  clearResetToken()
  showNotice('notice.resetDone')
}

function onResetClose() {
  clearResetToken()
}

onUnmounted(() => {
  window.clearTimeout(timer)
  window.clearTimeout(noticeTimer)
})

function showNotice(text) {
  notice.value = text
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    notice.value = ''
  }, 7000)
}

async function waitForPayment(sessionId) {
  if (!sessionId) {
    showNotice('notice.noSession')
    return
  }
  for (let index = 0; index < 40; index += 1) {
    try {
      const data = await getOrder(sessionId)
      if (data.member) {
        await refreshSession()
        showNotice('notice.memberActive')
        return
      }
      if (data.status === 'expired') {
        showNotice('notice.orderExpired')
        return
      }
    } catch (error) {
      if (error.message === '请先登录') break
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1500))
  }
  await refreshSession()
  showNotice('notice.paymentPending')
}

watch(url, (next, prev) => {
  if (next === prev) return
  clearTimer()
  attempt += 1
  meta.value = null
  selectedId.value = ''
  job.value = null
  phase.value = 'idle'
  jobError.value = ''
  parseError.value = ''
  if (!next.trim()) started.value = false
})

function clearTimer() {
  window.clearTimeout(timer)
  timer = 0
}

async function onParse() {
  const target = url.value.trim()
  clearTimer()
  attempt += 1
  meta.value = null
  job.value = null
  phase.value = 'idle'
  jobError.value = ''
  parseError.value = ''
  selectedId.value = ''
  if (!target) {
    parseError.value = 'error.emptyUrl'
    return
  }
  started.value = true
  parsing.value = true
  try {
    const data = await parseVideo(target)
    meta.value = data
    const preferred = data.formats.find((item) => !item.audio_only) || data.formats[0]
    selectedId.value = preferred ? preferred.format_id : ''
  } catch (error) {
    parseError.value = error.message || 'error.parseFailed'
  } finally {
    parsing.value = false
  }
}

async function onSave() {
  if (!meta.value || !selectedId.value || phase.value === 'saving') return
  const current = ++attempt
  phase.value = 'saving'
  jobError.value = ''
  job.value = null
  clearTimer()
  try {
    const created = await startDownload(url.value.trim(), selectedId.value)
    if (current !== attempt) return
    await poll(created.job_id, current, Date.now())
  } catch (error) {
    if (current !== attempt) return
    phase.value = 'failed'
    jobError.value = error.message || 'error.downloadFailed'
  }
}

async function poll(jobId, current, startedAt) {
  if (current !== attempt) return
  if (Date.now() - startedAt > 11 * 60 * 1000) {
    phase.value = 'failed'
    jobError.value = 'error.timeout'
    return
  }
  try {
    const data = await getJob(jobId)
    if (current !== attempt) return
    job.value = data
    if (data.status === 'finished') {
      phase.value = 'done'
      return
    }
    if (data.status === 'error') {
      phase.value = 'failed'
      jobError.value = data.error || 'error.downloadFailed'
      return
    }
    timer = window.setTimeout(() => poll(jobId, current, startedAt), 700)
  } catch (error) {
    if (current !== attempt) return
    phase.value = 'failed'
    jobError.value = error.message || 'error.downloadFailed'
  }
}
</script>

<template>
  <SiteHeader />
  <main class="px-4 pb-10 pt-16">
    <div class="mx-auto w-full max-w-[1080px]">
      <section v-if="!started" id="download" class="intro-rise scroll-mt-20 text-center">
        <p class="eyebrow">{{ t('app.eyebrow') }}</p>
        <h1 class="hero-title mx-auto mt-3 max-w-4xl">
          <span class="whitespace-nowrap">{{ t('app.heroLine1') }}</span><span class="whitespace-nowrap text-copper">{{ t('app.heroLine2') }}</span>
        </h1>
        <p class="mx-auto mt-3 max-w-[560px] text-[15px] leading-7 text-stone">
          {{ t('app.heroDesc') }}
        </p>
        <div class="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[12px] text-stone-light">
          <span>{{ t('app.factFree') }}</span>
          <span class="h-1 w-1 rounded-full bg-stone/30"></span>
          <span>{{ t('app.factCookie') }}</span>
          <span class="h-1 w-1 rounded-full bg-stone/30"></span>
          <span>{{ t('app.factLocal') }}</span>
        </div>
      </section>

      <div class="mx-auto w-full max-w-[680px]" :class="started ? 'mt-0' : 'mt-6'">
        <ParsePanel v-model="url" :busy="parsing" @submit="onParse" />
      </div>

      <ResultCard
        v-if="parsing || parseError || meta"
        :parsing="parsing"
        :error="jobError || parseError"
        :meta="meta"
        :selected-id="selectedId"
        :job="job"
        :phase="phase"
        @select="selectedId = $event"
        @save="onSave"
      />

      <WorkspaceView v-if="workspaceVisible" :url="url" />
    </div>

    <Highlights v-if="!started" />
    <FeatureGrid />
    <MemberGrid />
    <SiteFooter />
  </main>

  <div v-if="notice" class="pointer-events-none fixed inset-x-0 bottom-6 z-30 flex justify-center px-4">
    <div class="surface px-4 py-2 text-[13px] text-ink" role="status">{{ renderMessage(notice) }}</div>
  </div>

  <ResetPassword v-if="resetToken" :token="resetToken" @done="onResetDone" @close="onResetClose" />
</template>
