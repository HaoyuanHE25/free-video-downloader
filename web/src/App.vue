<script setup>
import { onUnmounted, ref } from 'vue'
import { getJob, parseVideo, startDownload } from './api.js'
import FeatureGrid from './components/FeatureGrid.vue'
import MemberGrid from './components/MemberGrid.vue'
import ParsePanel from './components/ParsePanel.vue'
import ResultCard from './components/ResultCard.vue'
import SiteFooter from './components/SiteFooter.vue'
import SiteHeader from './components/SiteHeader.vue'

const url = ref('')
const parsing = ref(false)
const parseError = ref('')
const meta = ref(null)
const selectedId = ref('')
const job = ref(null)
const phase = ref('idle')
const jobError = ref('')
let timer = 0
let attempt = 0

onUnmounted(() => window.clearTimeout(timer))

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
  selectedId.value = ''
  if (!target) {
    parseError.value = '请先粘贴一条公开视频链接'
    return
  }
  parsing.value = true
  parseError.value = ''
  try {
    const data = await parseVideo(target)
    meta.value = data
    const preferred = data.formats.find((item) => !item.audio_only) || data.formats[0]
    selectedId.value = preferred ? preferred.format_id : ''
  } catch (error) {
    parseError.value = error.message || '暂时无法解析这条链接'
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
    jobError.value = error.message || '下载没有完成，请重试'
  }
}

async function poll(jobId, current, started) {
  if (current !== attempt) return
  if (Date.now() - started > 11 * 60 * 1000) {
    phase.value = 'failed'
    jobError.value = '下载超时，请换一条较短的公开视频'
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
      jobError.value = data.error || '下载没有完成，请重试'
      return
    }
    timer = window.setTimeout(() => poll(jobId, current, started), 700)
  } catch (error) {
    if (current !== attempt) return
    phase.value = 'failed'
    jobError.value = error.message || '下载没有完成，请重试'
  }
}
</script>

<template>
  <SiteHeader />
  <main class="px-4 pb-10 pt-24">
    <section id="download" class="mx-auto max-w-5xl text-center">
      <h1 class="text-4xl font-black leading-tight tracking-tight text-ink">
        任意平台视频，<span class="text-copper">一键保存</span>
      </h1>
      <p class="mx-auto mt-3 max-w-xl text-base text-stone">粘贴公开链接，自选清晰度，电脑和手机都能下</p>
      <div class="mt-8">
        <ParsePanel v-model="url" :busy="parsing" @submit="onParse" />
      </div>
    </section>

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

    <FeatureGrid />
    <MemberGrid />
    <SiteFooter />
  </main>
</template>
