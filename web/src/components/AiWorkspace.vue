<script setup>
import { computed, defineAsyncComponent, ref } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps({
  url: { type: String, default: '' },
})

const { t } = useI18n()

const SummaryPanel = defineAsyncComponent(() => import('./SummaryPanel.vue'))
const SubtitlePanel = defineAsyncComponent(() => import('./SubtitlePanel.vue'))
const MindmapPanel = defineAsyncComponent(() => import('./MindmapPanel.vue'))
const QaPanel = defineAsyncComponent(() => import('./QaPanel.vue'))

const tabs = computed(() => [
  { id: 'summary', label: t('workspace.summary'), desc: t('workspace.summaryDesc') },
  { id: 'subtitle', label: t('workspace.subtitle'), desc: t('workspace.subtitleDesc') },
  { id: 'mindmap', label: t('workspace.mindmap'), desc: t('workspace.mindmapDesc') },
  { id: 'qa', label: t('workspace.qa'), desc: t('workspace.qaDesc') },
])

const panels = {
  summary: SummaryPanel,
  subtitle: SubtitlePanel,
  mindmap: MindmapPanel,
  qa: QaPanel,
}

const current = ref('summary')
const mounted = ref(['summary'])

function select(id) {
  current.value = id
  if (!mounted.value.includes(id)) mounted.value = [...mounted.value, id]
}

function onTabKey(event, index) {
  const forward = event.key === 'ArrowRight' || event.key === 'ArrowDown'
  const backward = event.key === 'ArrowLeft' || event.key === 'ArrowUp'
  if (!forward && !backward) return
  event.preventDefault()
  const list = tabs.value
  const next = (index + (forward ? 1 : -1) + list.length) % list.length
  select(list[next].id)
  const rail = event.currentTarget.closest('[role="tablist"]')
  rail?.querySelectorAll('[role="tab"]')[next]?.focus()
}
</script>

<template>
  <section id="workspace" class="mx-auto mt-4 w-full scroll-mt-20 sm:mt-5" aria-live="polite">
    <!-- 移动端 / 平板：横向吸顶标签 -->
    <div class="glass-bar sticky top-14 z-10 -mx-4 px-4 py-2 lg:hidden">
      <div class="segmented mx-auto flex w-full max-w-[560px]" role="tablist" :aria-label="t('workspace.tabsLabel')">
        <button
          v-for="(tab, index) in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          class="segmented-item flex min-w-0 flex-1 flex-col items-center gap-0.5 px-2 py-2.5 sm:px-4 sm:py-2"
          :class="current === tab.id ? 'segmented-item-active' : 'text-stone hover:bg-white/50 hover:text-ink'"
          :aria-selected="current === tab.id"
          :aria-controls="`work-panel-${tab.id}`"
          :tabindex="current === tab.id ? 0 : -1"
          @click="select(tab.id)"
          @keydown="onTabKey($event, index)"
        >
          <span class="flex items-center gap-1.5 text-[13px] font-semibold leading-5 sm:text-sm">
            <span
              v-if="current === tab.id"
              class="h-1.5 w-1.5 shrink-0 rounded-full bg-copper"
            ></span>
            {{ tab.label }}
          </span>
          <span
            class="hidden text-[10.5px] leading-4 tracking-[0.01em] sm:block"
            :class="current === tab.id ? 'text-stone' : 'text-stone-light/80'"
          >
            {{ tab.desc }}
          </span>
        </button>
      </div>
    </div>

    <!-- 桌面端：左侧垂直标签 + 右侧内容 -->
    <div class="lg:flex lg:items-start lg:gap-5">
      <aside class="hidden lg:sticky lg:top-20 lg:block lg:w-[236px] lg:shrink-0">
        <div class="tab-rail" role="tablist" :aria-label="t('workspace.tabsLabel')">
          <button
            v-for="(tab, index) in tabs"
            :key="tab.id"
            type="button"
            role="tab"
            class="tab-item"
            :class="{ 'tab-item-active': current === tab.id }"
            :aria-selected="current === tab.id"
            :aria-controls="`work-panel-${tab.id}`"
            :tabindex="current === tab.id ? 0 : -1"
            @click="select(tab.id)"
            @keydown="onTabKey($event, index)"
          >
            <span class="tab-icon">
              <svg
                v-if="tab.id === 'summary'"
                viewBox="0 0 24 24"
                class="h-4 w-4"
                aria-hidden="true"
              >
                <path d="M7 3.5h6.5L18 8v12.5H7z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M13 3.5V8h5M10 12h5M10 15.5h3.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
              <svg
                v-else-if="tab.id === 'subtitle'"
                viewBox="0 0 24 24"
                class="h-4 w-4"
                aria-hidden="true"
              >
                <rect x="3" y="5" width="18" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="1.7" />
                <path d="M7 10.5h4M13 10.5h4M7 14.5h7" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
              <svg
                v-else-if="tab.id === 'mindmap'"
                viewBox="0 0 24 24"
                class="h-4 w-4"
                aria-hidden="true"
              >
                <circle cx="6" cy="12" r="2.4" fill="none" stroke="currentColor" stroke-width="1.7" />
                <circle cx="18" cy="6" r="2.2" fill="none" stroke="currentColor" stroke-width="1.7" />
                <circle cx="18" cy="18" r="2.2" fill="none" stroke="currentColor" stroke-width="1.7" />
                <path d="M8.4 11.1 15.8 6.8M8.4 12.9 15.8 17.2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
              <svg
                v-else
                viewBox="0 0 24 24"
                class="h-4 w-4"
                aria-hidden="true"
              >
                <path d="M4 7a2.5 2.5 0 0 1 2.5-2.5h11A2.5 2.5 0 0 1 20 7v6a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.2v-3.2h-.5A2.5 2.5 0 0 1 3.5 13z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M8 10h8M8 13h4.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
              </svg>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[13.5px] font-semibold leading-5 text-ink">{{ tab.label }}</span>
              <span
                class="mt-0.5 block truncate text-[11px] leading-4"
                :class="current === tab.id ? 'text-stone' : 'text-stone-light'"
              >
                {{ tab.desc }}
              </span>
            </span>
            <span
              v-if="current === tab.id"
              class="h-1.5 w-1.5 shrink-0 rounded-full bg-copper"
            ></span>
          </button>
        </div>
        <p class="mt-3 px-2 text-[11px] leading-5 text-stone-light">{{ t('workspace.note') }}</p>
      </aside>

      <div class="mt-3 min-w-0 flex-1 sm:mt-4 lg:mt-0">
        <component
          :is="panels[id]"
          v-for="id in mounted"
          :id="`work-panel-${id}`"
          :key="id"
          v-show="current === id"
          :class="{ 'panel-fade': current === id }"
          :url="url"
        />
      </div>
    </div>
  </section>
</template>
