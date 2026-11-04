<script setup>
const features = [
  {
    title: '多平台',
    body: '公开页面能打开的链接，交给 yt-dlp 识别。不登录，也不接收平台 Cookie。',
    icon: 'platforms',
  },
  {
    title: '自选清晰度',
    body: '收成 1080p、720p、480p 和仅音频。默认选中不超过 1080p 的最佳一档。',
    icon: 'quality',
  },
  {
    title: '手机可用',
    body: '手机浏览器里同样能把文件保存到本地，不必先装桌面软件。',
    icon: 'phone',
  },
]
</script>

<template>
  <section id="quality" class="mx-auto mt-16 max-w-5xl">
    <h2 class="text-2xl font-black text-ink">能做什么</h2>
    <div class="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
      <article
        v-for="feature in features"
        :key="feature.title"
        class="rounded-xl border border-[rgba(28,25,23,0.06)] bg-card p-5 shadow-[0_12px_40px_rgba(120,72,32,0.06)]"
      >
        <svg v-if="feature.icon === 'platforms'" viewBox="0 0 24 24" class="h-6 w-6 text-copper" aria-hidden="true">
          <rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path d="M8 20h8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <svg v-else-if="feature.icon === 'quality'" viewBox="0 0 24 24" class="h-6 w-6 text-copper" aria-hidden="true">
          <path d="M4 7h16M4 12h10M4 17h13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <svg v-else viewBox="0 0 24 24" class="h-6 w-6 text-copper" aria-hidden="true">
          <rect x="7" y="2" width="10" height="20" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path d="M11 18h2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <h3 class="mt-4 text-lg font-bold text-ink">{{ feature.title }}</h3>
        <p class="mt-2 text-sm leading-6 text-stone">{{ feature.body }}</p>
      </article>
    </div>
  </section>
</template>
