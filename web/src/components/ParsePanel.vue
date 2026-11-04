<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'submit'])
</script>

<template>
  <form class="mx-auto w-full max-w-[600px]" @submit.prevent="emit('submit')">
    <label for="video-url" class="sr-only">公开视频链接</label>
    <div class="flex items-center rounded-full border border-line bg-white p-1 shadow-[0_8px_24px_rgba(120,72,32,0.06)] focus-within:border-copper">
      <input
        id="video-url"
        :value="modelValue"
        name="url"
        type="text"
        inputmode="url"
        autocomplete="off"
        placeholder="粘贴公开视频链接"
        class="min-h-11 min-w-0 flex-1 bg-transparent px-4 text-base text-ink outline-none placeholder:text-stone"
        @input="emit('update:modelValue', $event.target.value)"
      />
      <button
        type="submit"
        class="inline-flex min-h-11 shrink-0 cursor-pointer items-center justify-center rounded-full bg-ink px-5 text-sm font-medium text-cream transition hover:bg-copper-deep disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="busy"
      >
        {{ busy ? '解析中' : '解析' }}
      </button>
    </div>
  </form>
</template>
