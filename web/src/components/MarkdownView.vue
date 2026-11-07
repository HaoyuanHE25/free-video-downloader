<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

// 只允许安全标签；外链在新窗口打开，并阻断 opener。
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const props = defineProps({
  text: { type: String, default: '' },
  inline: { type: Boolean, default: false },
})

const html = computed(() => {
  const source = String(props.text || '').trim()
  if (!source) return ''
  try {
    return DOMPurify.sanitize(marked.parse(source, { async: false }), { USE_PROFILES: { html: true } })
  } catch {
    return DOMPurify.sanitize(source.replaceAll('<', '&lt;'))
  }
})
</script>

<template>
  <div class="markdown-body" :class="{ 'markdown-inline': inline }" v-html="html"></div>
</template>
