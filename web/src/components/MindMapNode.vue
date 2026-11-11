<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  collapsed: { type: Object, required: true },
})
const emit = defineEmits(['toggle'])

const { t } = useI18n()

const hasChildren = computed(() => (props.node.children || []).length > 0)
const open = computed(() => hasChildren.value && !props.collapsed[props.node.id])
</script>

<template>
  <div>
    <div
      class="flex items-start gap-2 rounded-lg px-2 py-1.5 transition"
      :class="depth === 0 ? 'bg-cream' : 'hover:bg-cream/70'"
    >
      <button
        v-if="hasChildren"
        type="button"
        class="mt-0.5 inline-flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-full border border-line bg-card text-xs text-ink"
        :aria-expanded="open"
        :aria-label="open ? t('mindmap.collapse') : t('mindmap.expand')"
        @click="emit('toggle', node.id)"
      >
        {{ open ? '−' : '+' }}
      </button>
      <span v-else class="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center text-xs text-stone">•</span>
      <div class="min-w-0">
        <p class="break-words text-sm font-medium leading-5 text-ink">{{ node.label }}</p>
        <p v-if="node.detail && !hasChildren" class="mt-1 break-words text-xs leading-5 text-stone">{{ node.detail }}</p>
      </div>
    </div>
    <div v-if="open" class="ml-4 border-l border-line pl-2">
      <MindMapNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :depth="depth + 1"
        :collapsed="collapsed"
        @toggle="emit('toggle', $event)"
      />
    </div>
  </div>
</template>
