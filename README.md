# 随下

在电脑或手机浏览器里粘贴公开视频链接，选一档清晰度，保存到本地。

第一期没有账号、支付和数据库。只下载你有权保存的公开内容，不提供账号登录代下。

产品范围见 [docs/需求分析.md](docs/需求分析.md)，实现和扩展点见 [docs/方案设计.md](docs/方案设计.md)，第一期完成情况见 [docs/项目总结.md](docs/项目总结.md)。

## 环境

- Python 3.11 及以上
- Node.js 20 及以上
- 本机 `ffmpeg` 在 `PATH` 中（合并 YouTube 这类分离的画面和声音）。没有 ffmpeg 时，仍然可以保存已经是单文件的清晰度和纯音频。
- 本机 `node` 在 `PATH` 中。YouTube 的清晰度列表依赖它和 yt-dlp 官方的挑战脚本；没有 node 时，部分平台只能看到很少的档位。
- 抖音不需要用户提供 Cookie。精选页 `modal_id`、`/video/数字` 和 `v.douyin.com` 短链都可以。图文暂不保存。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux 把激活命令换成 `source .venv/bin/activate`。

前端依赖：

```bash
cd web
npm install
```

## 启动

开两个终端。

```bash
.venv\Scripts\activate
python -m uvicorn app.main:app --port 8000
```

```bash
cd web
npm run dev
```

浏览器打开 `http://localhost:5173`。Vite 会把 `/api` 代理到 `8000`。

只看构建结果时：

```bash
cd web
npm run build
python -m uvicorn app.main:app --port 8000
```

FastAPI 发现 `web/dist` 后会在 `http://127.0.0.1:8000` 同时提供页面和接口。

## 验收

```bash
pytest
```

页面上再走一遍：

1. 空链接，卡片里出现「请先粘贴一条公开视频链接」。
2. 输入 `http://127.0.0.1/a` 或一段不是链接的文字，卡片里出现拒绝原因，且不会开始下载。
3. 粘贴一条短的公开链接，确认标题和 1080p / 720p / 480p / 仅音频 这些档位，切换选中态。
4. 点「保存到本地」，同一张卡片出现进度；完成后按钮变为「再次下载」，浏览器开始保存文件。
5. 把窗口缩到手机宽度，能力卡和会员卡变成单列，按钮和文字不超出屏幕。

会员卡上的「即将开放」不会扣费。批量、字幕翻译和视频总结都还没做。
