<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'submit'])
</script>

<template>
  <form class="w-full" @submit.prevent="emit('submit')">
    <label for="video-url" class="sr-only">公开视频链接</label>
    <div
      class="group glass-field flex items-center gap-2 rounded-[20px] p-1.5 pl-3.5 transition-[border-color,box-shadow] duration-200"
    >
      <svg viewBox="0 0 24 24" class="h-5 w-5 shrink-0 text-stone-light transition-colors duration-200 group-focus-within:text-stone" aria-hidden="true">
        <path
          d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"
          fill="none"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linecap="round"
        />
        <path
          d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"
          fill="none"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linecap="round"
        />
      </svg>
      <input
        id="video-url"
        :value="modelValue"
        name="url"
        type="text"
        inputmode="url"
        autocomplete="off"
        placeholder="粘贴公开视频链接"
        class="min-h-12 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-stone-light"
        @input="emit('update:modelValue', $event.target.value)"
      />
      <button type="submit" class="group/btn inline-flex min-h-12 shrink-0 items-center gap-1.5 rounded-[16px] border border-white/15 bg-ink/95 px-5 text-sm font-medium text-cream shadow-[inset_0_1px_0_rgba(255,255,255,0.18),0_10px_24px_-14px_rgba(20,25,40,0.6)] backdrop-blur-md transition-all duration-200 hover:bg-ink-deep active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50" :disabled="busy">
        {{ busy ? '解析中' : '解析' }}
        <svg viewBox="0 0 24 24" class="h-3.5 w-3.5 transition-transform duration-150 group-hover/btn:translate-x-0.5" aria-hidden="true">
          <path d="M5 12h13M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>
  </form>
</template>
