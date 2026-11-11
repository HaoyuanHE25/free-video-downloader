<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const features = computed(() => [
  {
    title: t('feature.platformsTitle'),
    body: t('feature.platformsBody'),
    icon: 'platforms',
  },
  {
    title: t('feature.qualityTitle'),
    body: t('feature.qualityBody'),
    icon: 'quality',
  },
  {
    title: t('feature.phoneTitle'),
    body: t('feature.phoneBody'),
    icon: 'phone',
  },
])
</script>

<template>
  <section id="capabilities" class="mx-auto mt-12 w-full max-w-[1080px] scroll-mt-20">
    <div class="flex items-center gap-3">
      <h2 class="shrink-0 text-[13px] font-semibold tracking-[0.04em] text-ink">{{ t('feature.heading') }}</h2>
      <span class="h-px flex-1 bg-line"></span>
      <p class="hidden shrink-0 text-[11px] text-stone-light sm:inline">{{ t('feature.note') }}</p>
    </div>
    <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
      <article
        v-for="feature in features"
        :key="feature.title"
        class="surface surface-hover flex items-start gap-3.5 p-5"
      >
        <svg v-if="feature.icon === 'platforms'" viewBox="0 0 24 24" class="h-9 w-9 shrink-0 rounded-[12px] border border-white/60 bg-white/45 p-2 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] backdrop-blur-md" aria-hidden="true">
          <rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path d="M8 20h8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <svg v-else-if="feature.icon === 'quality'" viewBox="0 0 24 24" class="h-9 w-9 shrink-0 rounded-[12px] border border-white/60 bg-white/45 p-2 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] backdrop-blur-md" aria-hidden="true">
          <path d="M4 7h16M4 12h10M4 17h13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <svg v-else viewBox="0 0 24 24" class="h-9 w-9 shrink-0 rounded-[12px] border border-white/60 bg-white/45 p-2 text-copper-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] backdrop-blur-md" aria-hidden="true">
          <rect x="7" y="2" width="10" height="20" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path d="M11 18h2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <div class="min-w-0">
          <h3 class="text-sm font-bold text-ink">{{ feature.title }}</h3>
          <p class="mt-1 text-xs leading-5 text-stone">{{ feature.body }}</p>
        </div>
      </article>
    </div>
  </section>
</template>
