<script setup>
import { ref, watch } from 'vue'
import MindMapNode from './MindMapNode.vue'

const props = defineProps({
  root: { type: Object, required: true },
})

const collapsed = ref({})

function toggle(id) {
  collapsed.value = { ...collapsed.value, [id]: !collapsed.value[id] }
}

function expandAll() {
  collapsed.value = {}
}

function collapseAll() {
  const map = {}
  const walk = (node) => {
    if (!node) return
    if ((node.children || []).length) map[node.id] = true
    for (const child of node.children || []) walk(child)
  }
  walk(props.root)
  collapsed.value = map
}

watch(
  () => props.root,
  () => {
    collapsed.value = {}
  },
)
</script>

<template>
  <div class="rounded-xl border border-line bg-cream/50 p-3">
    <div class="mb-2 flex justify-end gap-3 text-xs text-copper-deep">
      <button type="button" class="cursor-pointer" @click="expandAll">全部展开</button>
      <button type="button" class="cursor-pointer" @click="collapseAll">全部收起</button>
    </div>
    <MindMapNode :node="root" :collapsed="collapsed" @toggle="toggle" />
  </div>
</template>
