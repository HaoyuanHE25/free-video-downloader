<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { streamAsk } from '../summaryApi.js'
import MarkdownView from './MarkdownView.vue'

const props = defineProps({
  url: { type: String, default: '' },
})

const messages = ref([])
const input = ref('')
const busy = ref(false)
const status = ref('')
const error = ref('')
let controller = null

const ready = computed(() => Boolean(props.url.trim()))
const suggestions = ['这个视频讲了什么？', '列出最关键的结论', '有哪些值得注意的细节？']

onUnmounted(() => controller?.abort())

function resetChat() {
  controller?.abort()
  messages.value = []
  input.value = ''
  status.value = ''
  error.value = ''
  busy.value = false
}

async function onSend(text) {
  const question = String(text ?? input.value).trim()
  if (!question || busy.value) return
  const link = props.url.trim()
  if (!link) {
    error.value = '请先在上方粘贴视频链接'
    return
  }
  input.value = ''
  error.value = ''
  messages.value.push({ role: 'user', text: question })
  messages.value.push({ role: 'assistant', text: '', pending: true })
  const reply = messages.value[messages.value.length - 1]
  const history = messages.value
    .slice(0, -2)
    .slice(-6)
    .map((item) => ({ role: item.role, content: item.text }))

  busy.value = true
  status.value = '正在读取字幕'
  controller = new AbortController()
  try {
    await streamAsk(
      { question, history, url: link },
      (block) => {
        if (block.event === 'status') {
          status.value = block.data.message || ''
          reply.status = status.value
        } else if (block.event === 'delta' && block.data.target === 'answer') {
          reply.text += block.data.text || ''
        } else if (block.event === 'done') {
          reply.text = block.data.answer || reply.text
        } else if (block.event === 'error') {
          throw new Error(block.data.message || '回答没有生成，请重试')
        }
      },
      controller.signal,
    )
    if (!reply.text) throw new Error('回答没有生成，请重试')
  } catch (err) {
    if (err.name === 'AbortError') {
      if (!reply.text) messages.value.pop()
    } else {
      error.value = err.message || '回答没有生成，请重试'
      if (!reply.text) messages.value.pop()
    }
  } finally {
    reply.pending = false
    reply.status = ''
    busy.value = false
    status.value = ''
    controller = null
    if (messages.value.length > 12) messages.value.splice(0, messages.value.length - 12)
  }
}

function onStop() {
  controller?.abort()
}
</script>

<template>
  <article class="surface p-4 sm:p-6" aria-live="polite">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="flex items-center gap-2 text-xs text-stone">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="busy ? 'animate-pulse bg-copper' : 'bg-copper/60'"></span>
        {{ busy ? status || '正在处理' : messages.length ? '对话进行中' : '围绕视频内容连续追问' }}
      </p>
      <button v-if="messages.length" type="button" class="btn-quiet" @click="resetChat">
        重置对话
      </button>
    </div>

    <div v-if="!messages.length" class="mt-3 flex flex-wrap gap-2">
      <button v-for="item in suggestions" :key="item" type="button" class="chip" @click="onSend(item)">
        {{ item }}
      </button>
    </div>

    <div v-if="messages.length" class="mt-3 space-y-3">
      <div
        v-for="(item, index) in messages"
        :key="index"
        class="flex"
        :class="item.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          class="max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm leading-6"
          :class="item.role === 'user' ? 'bg-ink text-cream' : 'surface-inset text-ink'"
        >
          <MarkdownView v-if="item.role === 'assistant' && item.text" :text="item.text" />
          <p v-else class="whitespace-pre-wrap break-words">{{ item.text }}</p>
          <span v-if="item.pending" class="ml-0.5 animate-pulse text-copper">▍</span>
          <p v-if="item.pending && !item.text" class="text-xs text-stone">{{ item.status || '正在思考…' }}</p>
        </div>
      </div>
    </div>

    <p v-if="error" class="mt-3 rounded-xl border border-white/70 bg-white/50 px-3.5 py-2.5 text-sm text-copper-deep">
      {{ error }}
    </p>

    <p v-if="!ready && !busy" class="mt-3 text-xs text-stone">先在上方粘贴视频链接，再开始提问。</p>

    <form class="mt-4 flex items-center gap-2 border-t border-line pt-4" @submit.prevent="onSend()">
      <input
        v-model="input"
        type="text"
        maxlength="500"
        placeholder="针对视频内容提问…"
        class="field min-w-0 flex-1"
      />
      <button v-if="busy" type="button" class="btn-secondary shrink-0" @click="onStop">
        停止
      </button>
      <button v-else type="submit" class="btn-primary shrink-0" :disabled="!input.trim() || !ready">
        提问
      </button>
    </form>
  </article>
</template>
