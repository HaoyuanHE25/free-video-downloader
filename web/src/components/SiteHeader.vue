<template>
  <header class="glass-bar fixed inset-x-0 top-0 z-20 h-14 border-b border-white/50">
    <div class="mx-auto flex h-full max-w-[1080px] items-center gap-3 px-4">
      <span class="flex shrink-0 items-baseline gap-1.5">
        <span class="text-[17px] font-black tracking-[-0.02em] text-ink">随下</span>
        <span class="h-1.5 w-1.5 rounded-full bg-copper shadow-[0_0_8px_rgba(79,109,168,0.55)]"></span>
      </span>
      <nav class="ml-2 hidden items-center gap-0.5 text-[13px] text-stone sm:flex" aria-label="页面导航">
        <a
          href="#capabilities"
          class="rounded-full px-3 py-1.5 transition-colors duration-150 hover:bg-white/55 hover:text-ink"
        >
          能做什么
        </a>
        <a
          href="#member"
          class="rounded-full px-3 py-1.5 transition-colors duration-150 hover:bg-white/55 hover:text-ink"
        >
          会员
        </a>
      </nav>
      <div class="flex-1"></div>
      <button
        type="button"
        class="inline-flex min-h-9 shrink-0 cursor-not-allowed items-center gap-2 rounded-full border border-white/70 bg-white/50 px-3 text-[13px] text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] backdrop-blur-md"
        aria-disabled="true"
        @click.prevent
      >
        登录
        <span class="hidden text-[11px] font-medium text-copper-deep sm:inline">即将开放</span>
      </button>
    </div>
  </header>
</template>
