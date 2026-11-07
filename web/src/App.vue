<script setup>
import { computed, defineAsyncComponent, onUnmounted, ref, watch } from 'vue'
import { getJob, parseVideo, startDownload } from './api.js'
import FeatureGrid from './components/FeatureGrid.vue'
import MemberGrid from './components/MemberGrid.vue'
import ParsePanel from './components/ParsePanel.vue'
import SiteFooter from './components/SiteFooter.vue'
import SiteHeader from './components/SiteHeader.vue'

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

onUnmounted(() => window.clearTimeout(timer))

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
    parseError.value = '请先粘贴一条公开视频链接'
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

async function poll(jobId, current, startedAt) {
  if (current !== attempt) return
  if (Date.now() - startedAt > 11 * 60 * 1000) {
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
    timer = window.setTimeout(() => poll(jobId, current, startedAt), 700)
  } catch (error) {
    if (current !== attempt) return
    phase.value = 'failed'
    jobError.value = error.message || '下载没有完成，请重试'
  }
}
</script>

<template>
  <SiteHeader />
  <main class="px-4 pb-10 pt-16">
    <div class="mx-auto w-full max-w-[1080px]">
      <section v-if="!started" id="download" class="intro-rise scroll-mt-20 text-center">
        <p class="eyebrow">下载与解读</p>
        <h1 class="hero-title mx-auto mt-3 max-w-4xl">
          <span class="whitespace-nowrap">任意平台视频，</span><span class="whitespace-nowrap text-copper">一键保存</span>
        </h1>
        <p class="mx-auto mt-3 max-w-[560px] text-[15px] leading-7 text-stone">
          粘贴一条公开链接，下载、总结、字幕、导图与问答共用同一条地址
        </p>
        <div class="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[12px] text-stone-light">
          <span>免登录</span>
          <span class="h-1 w-1 rounded-full bg-stone/30"></span>
          <span>不接收平台 Cookie</span>
          <span class="h-1 w-1 rounded-full bg-stone/30"></span>
          <span>文件保存在本地</span>
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

    <FeatureGrid />
    <MemberGrid />
    <SiteFooter />
  </main>
</template>
