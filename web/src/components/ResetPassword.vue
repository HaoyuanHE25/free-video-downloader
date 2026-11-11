<script setup>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { resetPassword } from '../api.js'
import { renderMessage } from '../i18n/messages.js'
import { refreshSession } from '../session.js'

const props = defineProps({
  token: { type: String, required: true },
})
const emit = defineEmits(['done', 'close'])

const { t } = useI18n()

const password = ref('')
const confirm = ref('')
const busy = ref(false)
const error = ref('')
const inputRef = ref(null)

onMounted(async () => {
  await nextTick()
  inputRef.value?.focus()
})

async function submit() {
  if (busy.value) return
  if (password.value.length < 8) {
    error.value = 'error.passwordTooShort'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'error.passwordMismatch'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await resetPassword(props.token, password.value)
    await refreshSession({ force: true })
    emit('done')
  } catch (err) {
    error.value = err.message || 'error.resetFailed'
  } finally {
    busy.value = false
  }
}

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-40 flex items-end justify-center bg-ink/25 px-4 pb-6 pt-20 backdrop-blur-sm sm:items-center sm:pb-20">
      <div class="surface panel-fade w-full max-w-[420px] p-5 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="reset-title">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <h2 id="reset-title" class="text-[15px] font-bold text-ink">{{ t('reset.title') }}</h2>
            <p class="mt-1 text-[12px] leading-5 text-stone">{{ t('reset.hint') }}</p>
          </div>
          <button type="button" class="btn-quiet -mr-1 -mt-1 shrink-0" :aria-label="t('common.close')" @click="emit('close')">
            <svg viewBox="0 0 24 24" class="h-4 w-4" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </button>
        </div>

        <form class="mt-4" @submit.prevent="submit">
          <label class="field-label" for="reset-password">{{ t('reset.label') }}</label>
          <input
            id="reset-password"
            ref="inputRef"
            v-model="password"
            type="password"
            class="field"
            autocomplete="new-password"
            :placeholder="t('auth.passwordPlaceholder')"
            maxlength="72"
          />
          <label class="field-label mt-3" for="reset-confirm">{{ t('reset.confirmLabel') }}</label>
          <input
            id="reset-confirm"
            v-model="confirm"
            type="password"
            class="field"
            autocomplete="new-password"
            :placeholder="t('auth.confirmPlaceholder')"
            maxlength="72"
          />
          <p v-if="error" class="mt-2 text-[12px] text-[#b4534f]">{{ renderMessage(error) }}</p>
          <button type="submit" class="btn-primary mt-4 w-full" :disabled="busy">
            {{ busy ? t('reset.busy') : t('reset.submit') }}
          </button>
        </form>
      </div>
    </div>
  </Teleport>
</template>
