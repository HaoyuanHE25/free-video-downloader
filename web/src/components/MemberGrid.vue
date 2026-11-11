<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { startCheckout } from '../api.js'
import { renderMessage } from '../i18n/messages.js'
import { memberPanel, openAuth, refreshSession, session } from '../session.js'

const { t } = useI18n()

const busy = ref(false)
const error = ref('')

const price = computed(() => session.price?.label || '¥9.9')

async function buy() {
  if (busy.value) return
  // 缓存状态未确认时先问服务端，避免拿被篡改或过期的本地状态下单
  if (session.stale) await refreshSession({ force: true })
  if (session.member) return
  if (!session.user) {
    openAuth()
    return
  }
  busy.value = true
  error.value = ''
  try {
    const data = await startCheckout()
    if (data.url) {
      window.location.href = data.url
      return
    }
    error.value = 'error.payUnavailable'
  } catch (err) {
    error.value = err.message || 'error.payUnavailable'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <details
    id="member"
    class="group mx-auto mt-8 w-full max-w-[1080px] scroll-mt-20"
    :open="memberPanel.open"
    @toggle="memberPanel.open = $event.target.open"
  >
    <summary class="surface flex cursor-pointer list-none items-center gap-2 px-4 py-3 transition-colors duration-150 hover:border-white [&::-webkit-details-marker]:hidden">
      <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-copper"></span>
      <span class="text-[13px] font-semibold text-ink">{{ t('member.heading') }}</span>
      <span class="hidden text-[11px] text-stone sm:inline">{{ t('member.summaryNote') }}</span>
      <span
        v-if="session.member"
        class="ml-auto shrink-0 rounded-full bg-copper-soft px-2 py-0.5 text-[11px] font-medium text-copper-deep"
      >
        {{ t('member.active') }}
      </span>
      <svg
        v-else
        viewBox="0 0 24 24"
        class="ml-auto h-4 w-4 shrink-0 text-stone-light transition-transform duration-200 group-open:rotate-180"
        aria-hidden="true"
      >
        <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </summary>

    <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
      <article class="surface p-5">
        <p class="text-[11px] font-medium tracking-[0.04em] text-copper-deep">{{ t('member.freeLabel') }}</p>
        <h3 class="mt-1 text-[15px] font-bold text-ink">{{ t('member.freeTitle') }}</h3>
        <ul class="mt-3 space-y-1.5 text-sm text-ink">
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.freeItemConcurrency') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.freeItemSize') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.freeItemDuration') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.freeItemFeatures') }}
          </li>
        </ul>
      </article>

      <article class="surface p-5">
        <div class="flex items-baseline justify-between gap-3">
          <p class="text-[11px] font-medium tracking-[0.04em] text-copper-deep">{{ t('member.proLabel') }}</p>
          <p class="text-[11px] text-stone-light">{{ t('member.proNote') }}</p>
        </div>
        <h3 class="mt-1 text-[15px] font-bold text-ink">
          {{ t('member.proTitle', { price }) }}
        </h3>
        <ul class="mt-3 space-y-1.5 text-sm text-ink">
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.proItemUnlimited') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.proItemConcurrency') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.proItemSize') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.proItemDuration') }}
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            {{ t('member.proItemFeatures') }}
          </li>
        </ul>
        <button
          type="button"
          class="btn-primary mt-4 w-full"
          :disabled="busy || session.member"
          @click="buy"
        >
          <template v-if="session.member">{{ t('member.buyActive') }}</template>
          <template v-else-if="!session.user">{{ t('member.buySignIn') }}</template>
          <template v-else>{{ busy ? t('member.buyBusy') : t('member.buy', { price }) }}</template>
        </button>
        <p v-if="error" class="mt-2 text-[12px] leading-5 text-[#b4534f]">{{ renderMessage(error) }}</p>
        <p class="mt-2 text-[11px] leading-5 text-stone-light">
          {{ t('member.payNote') }}
        </p>
      </article>
    </div>
  </details>
</template>
