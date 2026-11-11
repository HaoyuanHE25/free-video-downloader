<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <footer class="mx-auto mt-10 w-full max-w-[1080px] border-t border-line py-6">
    <div class="flex flex-col gap-2 text-xs text-stone-light sm:flex-row sm:items-center sm:justify-between">
      <p class="flex items-center gap-1.5 text-sm font-black tracking-[-0.01em] text-ink">
        {{ t('common.brand') }}
        <span class="h-1 w-1 rounded-full bg-copper"></span>
      </p>
      <p>{{ t('footer.note') }}</p>
    </div>
  </footer>
</template>
