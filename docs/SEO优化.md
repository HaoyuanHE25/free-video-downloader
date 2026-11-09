# 随下：SEO 基础优化

本文记录页面对搜索引擎的一次基础优化，目标是让「在线视频下载 / AI 视频总结」一类内容能被百度、Google、Bing 收录并尽可能靠前展示。改动只扩展抓取与展示信息，不改变任何现有功能，也不改渲染架构。

## 做了什么

| 位置 | 内容 |
| --- | --- |
| `web/index.html` 头部 | title 主关键词「在线视频下载 / AI 总结」靠前；description 带价值主张与行动点；keywords、robots、canonical；Open Graph 与 Twitter Card；`WebApplication` 结构化数据（JSON-LD，含应用名、免费属性、功能清单） |
| `web/public/robots.txt` | 允许抓取、屏蔽 `/api/`、声明 sitemap 地址 |
| `web/public/sitemap.xml` | 首页 sitemap |

`web/public/` 下的文件会由 Vite 构建原样复制进 `web/dist/`；生产环境由 FastAPI 静态托管 `web/dist`，因此它们分别对应站点根路径的 `/robots.txt` 与 `/sitemap.xml`，无需改后端代码。

message/关键信息集中在首页，与 [需求分析.md](需求分析.md)、[方案设计.md](方案设计.md) 的产品口径一致；未新增子页面，因此 sitemap 目前只有首页一个入口。

## 上线前必须替换占位域名

域名目前用占位符 `https://example.com`，分布在三处。拿到正式域名后全局替换，并保持末尾带 `/`：

1. `web/index.html`：`<link rel="canonical">`、`og:url`、JSON-LD 里的 `url`
2. `web/public/robots.txt`：`Sitemap:` 行
3. `web/public/sitemap.xml`：`<loc>`

## 已知限制

- 页面仍是纯客户端渲染（SPA），HTML 只有一个空的 `#app` 容器。Google 能渲染 JS 但偏慢，百度、Bing 对 JS 渲染支持较弱，可能抓不到「下载 / 总结 / 字幕 / 导图」等正文。要彻底解决需预渲染或服务端渲染（SSR），属独立改动，未纳入本次范围。
- 暂无 `og:image` 与 favicon，社交分享不会显示缩略图。
- `keywords` meta 仅供部分引擎参考，Google 已基本忽略；依赖它做排名不可靠，应以正文内容为主。

## 上线后建议

- 用 Rich Results Test（会渲染 JavaScript）或百度资源平台校验结构化数据。
- 向百度资源平台、Google Search Console、Bing Webmaster Tools 提交 sitemap。
- 没有站长工具时，也可直接向各引擎主动提交首页 URL 加速收录。