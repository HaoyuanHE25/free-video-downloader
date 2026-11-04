<script setup>
const links = [
  { href: '#download', label: '下载' },
  { href: '#quality', label: '清晰度' },
  { href: '#member', label: '会员' },
]
</script>

<template>
  <header class="fixed inset-x-0 top-0 z-20 h-14 border-b border-[rgba(28,25,23,0.06)] bg-cream/90 backdrop-blur">
    <div class="mx-auto flex h-full max-w-5xl items-center gap-3 px-4">
      <a href="#download" class="shrink-0 text-lg font-black tracking-tight text-ink">随下</a>
      <nav class="flex min-w-0 flex-1 items-center gap-4 overflow-x-auto text-sm" aria-label="页面">
        <a
          v-for="link in links"
          :key="link.href"
          :href="link.href"
          class="shrink-0 cursor-pointer text-stone transition hover:text-copper"
        >
          {{ link.label }}
        </a>
      </nav>
      <button
        type="button"
        class="inline-flex min-h-11 shrink-0 cursor-not-allowed items-center gap-2 rounded-full border border-line bg-white px-3 text-sm text-ink"
        aria-disabled="true"
        @click.prevent
      >
        登录
        <span class="text-xs font-medium text-copper-deep">即将开放</span>
      </button>
    </div>
  </header>
</template>
