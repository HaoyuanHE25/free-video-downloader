<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { logout } from '../api.js'
import { LOCALES, currentLocale, setLocale } from '../i18n/index.js'
import { memberPanel, openAuth, refreshSession, session } from '../session.js'
import AuthDialog from './AuthDialog.vue'

const { t } = useI18n()
const busy = ref(false)
const locale = computed(() => currentLocale())

async function signOut() {
  if (busy.value) return
  busy.value = true
  try {
    await logout()
  } catch {
    // 退出失败也刷新一次，避免界面与服务端状态不一致
  } finally {
    await refreshSession()
    busy.value = false
  }
}
</script>

<template>
  <header class="glass-bar fixed inset-x-0 top-0 z-20 h-14 border-b border-white/50">
    <div class="mx-auto flex h-full max-w-[1080px] items-center gap-2 px-3 sm:gap-3 sm:px-4">
      <span class="flex shrink-0 items-baseline gap-1.5">
        <span class="text-[17px] font-black tracking-[-0.02em] text-ink">{{ t('common.brand') }}</span>
        <span class="h-1.5 w-1.5 rounded-full bg-copper shadow-[0_0_8px_rgba(79,109,168,0.55)]"></span>
      </span>
      <nav class="ml-2 hidden items-center gap-0.5 text-[13px] text-stone sm:flex" :aria-label="t('header.navLabel')">
        <a
          href="#capabilities"
          class="rounded-full px-3 py-1.5 transition-colors duration-150 hover:bg-white/55 hover:text-ink"
        >
          {{ t('header.capabilities') }}
        </a>
        <a
          href="#member"
          class="rounded-full px-3 py-1.5 transition-colors duration-150 hover:bg-white/55 hover:text-ink"
          @click="memberPanel.open = true"
        >
          {{ t('header.member') }}
        </a>
      </nav>
      <div class="flex flex-1 items-center justify-end gap-1.5">
        <div class="lang-switch shrink-0" role="group" :aria-label="t('header.language')">
          <button
            v-for="item in LOCALES"
            :key="item.code"
            type="button"
            class="lang-item"
            :class="{ 'lang-item-active': locale === item.code }"
            :aria-pressed="locale === item.code"
            :title="t('header.switchTo', { name: item.name })"
            @click="setLocale(item.code)"
          >
            {{ item.short }}
          </button>
        </div>
        <template v-if="session.user">
          <span class="hidden max-w-[180px] truncate text-[12px] text-stone md:inline">
            {{ session.user.email }}
          </span>
          <span
            class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium"
            :class="session.member ? 'bg-copper-soft text-copper-deep' : 'border border-white/70 bg-white/55 text-stone'"
          >
            {{ session.member ? t('header.memberBadge') : t('header.freeBadge') }}
          </span>
          <button type="button" class="btn-quiet shrink-0" :disabled="busy" @click="signOut">
            {{ t('header.signOut') }}
          </button>
        </template>
        <button
          v-else-if="session.ready"
          type="button"
          class="btn-secondary min-h-9 shrink-0 px-3 text-[13px]"
          @click="openAuth"
        >
          {{ t('header.signIn') }}
        </button>
        <span v-else class="inline-block h-9 w-[62px]" aria-hidden="true"></span>
      </div>
    </div>
  </header>
  <AuthDialog />
</template>

<style scoped>
.lang-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.45);
  padding: 2px;
}

.lang-item {
  cursor: pointer;
  border-radius: 9999px;
  padding: 2px 7px;
  font-size: 11px;
  line-height: 16px;
  color: var(--color-stone);
  transition: color 0.15s ease, background-color 0.15s ease;
}

.lang-item:hover {
  color: var(--color-ink);
}

.lang-item-active {
  background: var(--color-copper-soft);
  color: var(--color-copper-deep);
  font-weight: 500;
}
</style>
