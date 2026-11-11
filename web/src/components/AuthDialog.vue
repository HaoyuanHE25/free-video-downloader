<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { loginWithPassword, registerAccount, requestPasswordReset } from '../api.js'
import { renderMessage } from '../i18n/messages.js'
import { authPanel, closeAuth, refreshSession } from '../session.js'

const { t } = useI18n()

const mode = ref('login')
const email = ref('')
const password = ref('')
const confirm = ref('')
const resetLink = ref('')
const busy = ref(false)
const error = ref('')
const inputRef = ref(null)

const MODE_KEYS = {
  login: 'login',
  register: 'register',
  reset: 'reset',
  'reset-sent': 'resetSent',
}

const copy = computed(() => {
  const key = MODE_KEYS[mode.value]
  const hasAction = mode.value !== 'reset-sent'
  return {
    title: t(`auth.${key}Title`),
    hint: t(`auth.${key}Hint`),
    action: hasAction ? t(`auth.${key}Action`) : '',
    busy: hasAction ? t(`auth.${key}Busy`) : '',
  }
})

watch(
  () => authPanel.open,
  async (open) => {
    if (!open) return
    mode.value = 'login'
    password.value = ''
    confirm.value = ''
    resetLink.value = ''
    busy.value = false
    error.value = ''
    await nextTick()
    inputRef.value?.focus()
  },
)

function switchMode(next) {
  mode.value = next
  password.value = ''
  confirm.value = ''
  error.value = ''
  nextTick(() => inputRef.value?.focus())
}

async function submit() {
  if (busy.value) return
  const mail = email.value.trim()
  if (!mail) {
    error.value = 'error.emailRequired'
    return
  }
  if (mode.value === 'reset') {
    busy.value = true
    error.value = ''
    try {
      const data = await requestPasswordReset(mail)
      resetLink.value = data.reset_url || ''
      mode.value = 'reset-sent'
    } catch (err) {
      error.value = err.message || 'error.resetLinkFailed'
    } finally {
      busy.value = false
    }
    return
  }
  if (password.value.length < 8) {
    error.value = 'error.passwordTooShort'
    return
  }
  if (mode.value === 'register' && password.value !== confirm.value) {
    error.value = 'error.passwordMismatch'
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (mode.value === 'register') await registerAccount(mail, password.value)
    else await loginWithPassword(mail, password.value)
    await refreshSession({ force: true })
    closeAuth()
  } catch (err) {
    error.value = err.message || 'error.actionFailed'
  } finally {
    busy.value = false
  }
}

function onKeydown(event) {
  if (event.key === 'Escape' && authPanel.open) closeAuth()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="authPanel.open"
      class="fixed inset-0 z-40 flex items-end justify-center bg-ink/25 px-4 pb-6 pt-20 backdrop-blur-sm sm:items-center sm:pb-20"
      @mousedown.self="closeAuth"
    >
      <div
        class="surface panel-fade w-full max-w-[420px] p-5 sm:p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
      >
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <h2 id="auth-title" class="text-[15px] font-bold text-ink">{{ copy.title }}</h2>
            <p class="mt-1 text-[12px] leading-5 text-stone">{{ copy.hint }}</p>
          </div>
          <button type="button" class="btn-quiet -mr-1 -mt-1 shrink-0" :aria-label="t('common.close')" @click="closeAuth">
            <svg viewBox="0 0 24 24" class="h-4 w-4" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </button>
        </div>

        <div v-if="mode === 'reset-sent'" class="mt-4">
          <div class="surface-inset px-3 py-2.5 text-[12px] leading-5 text-stone">
            {{ t('auth.resetSentNote') }}
          </div>
          <p class="mt-2 break-all text-[11px] leading-5 text-stone-light">{{ resetLink }}</p>
          <a :href="resetLink" class="btn-primary mt-3 w-full">{{ t('auth.resetSentOpen') }}</a>
          <button type="button" class="btn-secondary mt-3 w-full" @click="switchMode('login')">{{ t('auth.resetSentBack') }}</button>
        </div>

        <form v-else class="mt-4" @submit.prevent="submit">
          <label class="field-label" for="auth-email">{{ t('auth.email') }}</label>
          <input
            id="auth-email"
            ref="inputRef"
            v-model="email"
            type="email"
            class="field"
            autocomplete="email"
            placeholder="you@example.com"
            maxlength="254"
          />

          <template v-if="mode !== 'reset'">
            <label class="field-label mt-3" for="auth-password">{{ t('auth.password') }}</label>
            <input
              id="auth-password"
              v-model="password"
              type="password"
              class="field"
              :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
              :placeholder="t('auth.passwordPlaceholder')"
              maxlength="72"
            />
          </template>

          <template v-if="mode === 'register'">
            <label class="field-label mt-3" for="auth-confirm">{{ t('auth.confirm') }}</label>
            <input
              id="auth-confirm"
              v-model="confirm"
              type="password"
              class="field"
              autocomplete="new-password"
              :placeholder="t('auth.confirmPlaceholder')"
              maxlength="72"
            />
          </template>

          <p v-if="error" class="mt-2 text-[12px] text-[#b4534f]">{{ renderMessage(error) }}</p>
          <button type="submit" class="btn-primary mt-4 w-full" :disabled="busy">
            {{ busy ? copy.busy : copy.action }}
          </button>

          <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-[12px]">
            <template v-if="mode === 'login'">
              <button type="button" class="text-stone underline-offset-2 hover:text-ink hover:underline" @click="switchMode('reset')">
                {{ t('auth.forgot') }}
              </button>
              <button type="button" class="text-copper-deep underline-offset-2 hover:underline" @click="switchMode('register')">
                {{ t('auth.noAccount') }}
              </button>
            </template>
            <template v-else-if="mode === 'register'">
              <span class="text-stone-light">{{ t('auth.hasAccount') }}</span>
              <button type="button" class="text-copper-deep underline-offset-2 hover:underline" @click="switchMode('login')">
                {{ t('auth.directLogin') }}
              </button>
            </template>
            <template v-else>
              <span class="text-stone-light">{{ t('auth.remembered') }}</span>
              <button type="button" class="text-copper-deep underline-offset-2 hover:underline" @click="switchMode('login')">
                {{ t('auth.backToLogin') }}
              </button>
            </template>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>
