<template>
  <section id="member" class="mx-auto mt-16 max-w-5xl">
    <h2 class="text-2xl font-black text-ink">会员</h2>
    <p class="mt-2 text-sm text-stone">第一期不收款。免费档现在就能用，会员能力还没开放。</p>
    <div class="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2">
      <article class="rounded-xl border border-[rgba(28,25,23,0.06)] bg-card p-5 shadow-[0_12px_40px_rgba(120,72,32,0.06)]">
        <p class="text-xs font-medium text-ink">免费可用</p>
        <h3 class="mt-2 text-xl font-black text-ink">当前就能保存</h3>
        <ul class="mt-4 space-y-2 text-sm text-ink">
          <li>单条公开链接</li>
          <li>自选清晰度</li>
          <li>保存到本地</li>
        </ul>
      </article>
      <article class="rounded-xl border border-[rgba(28,25,23,0.06)] bg-card p-5 shadow-[0_12px_40px_rgba(120,72,32,0.06)]">
        <p class="text-xs font-medium text-copper-deep">即将开放</p>
        <h3 class="mt-2 text-xl font-black text-ink">会员预告</h3>
        <ul class="mt-4 space-y-2 text-sm text-ink">
          <li>批量链接</li>
          <li>字幕翻译</li>
          <li>视频总结</li>
        </ul>
        <button
          type="button"
          class="mt-5 inline-flex min-h-11 cursor-not-allowed items-center rounded-full border border-copper-deep px-5 text-sm font-medium text-copper-deep"
          aria-disabled="true"
          @click.prevent
        >
          即将开放
        </button>
      </article>
    </div>
  </section>
</template>
