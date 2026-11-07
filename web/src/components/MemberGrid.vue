<template>
  <details id="member" class="group mx-auto mt-8 w-full max-w-[1080px] scroll-mt-20">
    <summary class="surface flex cursor-pointer list-none items-center gap-2 px-4 py-3 transition-colors duration-150 hover:border-white [&::-webkit-details-marker]:hidden">
      <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-copper"></span>
      <span class="text-[13px] font-semibold text-ink">会员与后续计划</span>
      <span class="hidden text-[11px] text-stone sm:inline">第一期不收款，免费档现在就能用</span>
      <svg viewBox="0 0 24 24" class="ml-auto h-4 w-4 shrink-0 text-stone-light transition-transform duration-200 group-open:rotate-180" aria-hidden="true">
        <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </summary>

    <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
      <article class="surface p-5">
        <p class="text-[11px] font-medium tracking-[0.04em] text-copper-deep">免费可用</p>
        <h3 class="mt-1 text-[15px] font-bold text-ink">当前就能保存</h3>
        <ul class="mt-3 space-y-1.5 text-sm text-ink">
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            单条公开链接
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            自选清晰度
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            保存到本地
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            视频总结
          </li>
        </ul>
      </article>
      <article class="surface p-5">
        <p class="text-[11px] font-medium tracking-[0.04em] text-copper-deep">即将开放</p>
        <h3 class="mt-1 text-[15px] font-bold text-ink">会员预告</h3>
        <ul class="mt-3 space-y-1.5 text-sm text-ink">
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            批量链接
          </li>
          <li class="flex items-start gap-2">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-copper"></span>
            字幕翻译
          </li>
        </ul>
        <button
          type="button"
          class="mt-4 inline-flex min-h-9 cursor-not-allowed items-center rounded-full border border-white/70 bg-white/45 px-4 text-sm font-medium text-stone shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] backdrop-blur-md"
          aria-disabled="true"
          @click.prevent
        >
          即将开放
        </button>
      </article>
    </div>
  </details>
</template>
