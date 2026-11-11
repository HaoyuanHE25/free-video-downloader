<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { session } from '../session.js'

const { t } = useI18n()

const price = computed(() => session.price?.label || '¥9.9')

const highlights = computed(() => [
  {
    value: t('highlights.quotaValue'),
    note: t('highlights.quotaNote'),
    title: t('highlights.quotaTitle'),
    body: t('highlights.quotaBody'),
    icon: 'quota',
  },
  {
    value: t('highlights.qualityValue'),
    note: t('highlights.qualityNote'),
    title: t('highlights.qualityTitle'),
    body: t('highlights.qualityBody'),
    icon: 'quality',
  },
  {
    value: t('highlights.toolsValue'),
    note: t('highlights.toolsNote'),
    title: t('highlights.toolsTitle'),
    body: t('highlights.toolsBody'),
    icon: 'all',
  },
  {
    value: price.value,
    note: t('highlights.memberNote'),
    title: t('highlights.memberTitle'),
    body: t('highlights.memberBody'),
    icon: 'member',
  },
])
</script>

<template>
  <section id="highlights" class="mx-auto mt-10 w-full max-w-[1080px] scroll-mt-20" aria-labelledby="highlights-title">
    <div class="flex items-center gap-3">
      <h2 id="highlights-title" class="shrink-0 text-[13px] font-semibold tracking-[0.04em] text-ink">{{ t('highlights.heading') }}</h2>
      <span class="h-px flex-1 bg-line"></span>
      <p class="hidden shrink-0 text-[11px] text-stone-light sm:inline">{{ t('highlights.note') }}</p>
    </div>

    <div class="mt-4 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      <article
        v-for="item in highlights"
        :key="item.title"
        class="surface surface-hover relative overflow-hidden p-3.5 sm:p-5"
      >
        <span class="pointer-events-none absolute -right-10 -top-12 h-24 w-24 rounded-full bg-copper/10 blur-2xl"></span>
        <svg
          v-if="item.icon === 'quota'"
          viewBox="0 0 24 24"
          class="relative h-8 w-8 shrink-0 rounded-[10px] border border-white/60 bg-white/55 p-1.5 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]"
          aria-hidden="true"
        >
          <path d="M12 7v5l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.6" />
        </svg>
        <svg
          v-else-if="item.icon === 'quality'"
          viewBox="0 0 24 24"
          class="relative h-8 w-8 shrink-0 rounded-[10px] border border-white/60 bg-white/55 p-1.5 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]"
          aria-hidden="true"
        >
          <path d="M4 18V9M10 18V5M16 18v-6M22 18h-2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <svg
          v-else-if="item.icon === 'all'"
          viewBox="0 0 24 24"
          class="relative h-8 w-8 shrink-0 rounded-[10px] border border-white/60 bg-white/55 p-1.5 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]"
          aria-hidden="true"
        >
          <rect x="3.5" y="3.5" width="7" height="7" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.7" />
          <rect x="13.5" y="3.5" width="7" height="7" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.7" />
          <rect x="3.5" y="13.5" width="7" height="7" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.7" />
          <rect x="13.5" y="13.5" width="7" height="7" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.7" />
        </svg>
        <svg
          v-else
          viewBox="0 0 24 24"
          class="relative h-8 w-8 shrink-0 rounded-[10px] border border-white/60 bg-white/55 p-1.5 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]"
          aria-hidden="true"
        >
          <path d="M12 3l2.4 5 5.6.8-4 3.9.9 5.5L12 15.5 7.1 18.2l.9-5.5-4-3.9L9.6 8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
        </svg>

        <p class="relative mt-2.5 flex items-baseline gap-1">
          <span class="text-[24px] font-black leading-none tracking-[-0.03em] text-ink sm:text-[30px]">{{ item.value }}</span>
          <span class="text-[11px] font-medium text-copper-deep">{{ item.note }}</span>
        </p>
        <h3 class="relative mt-2 text-[13px] font-bold text-ink">{{ item.title }}</h3>
        <p class="relative mt-1 text-[11px] leading-5 text-stone">{{ item.body }}</p>
      </article>
    </div>
  </section>
</template>
