import { i18n } from './index.js'

// 服务端返回的中文提示 → 语言包 key。
// 后端不感知语言，统一返回中文；前端在展示边界翻译，未知文案原样显示。
const SERVER_MESSAGES = {
  '链接无效': 'server.invalidUrl',
  '不支持本机或内网地址': 'server.privateAddress',
  '清晰度选项无效': 'server.invalidFormat',
  '没有可保存的公开清晰度': 'server.noFormat',
  '暂时无法解析这条链接': 'error.parseFailed',
  '平台暂不支持': 'server.unsupportedPlatform',
  '这个内容需要登录，本站只保存公开视频': 'server.loginRequired',
  'YouTube 暂时把这次访问当成了机器人，请稍后再试': 'server.youtubeBlocked',
  '解析超时，请稍后再试': 'server.parseTimeout',
  '这个封面不能转发': 'server.coverForbidden',
  '封面暂时取不到': 'server.coverUnavailable',
  '服务器还没有安装解析引擎': 'server.engineMissing',
  '当前下载较多，请稍后再试': 'server.busy',
  '下载超时，请换一条较短的公开视频': 'error.timeout',
  '下载没有完成，请重试': 'error.downloadFailed',
  '这条是图文，暂时只能保存视频': 'server.imagePost',
  '这条链接里没有视频': 'server.noVideo',
  '这条视频暂时取不到，可能不是公开视频': 'server.videoUnavailable',
  '需要安装 ffmpeg，才能把画面和声音合成一个文件': 'server.ffmpegNeeded',
  '任务不存在或已过期': 'server.jobMissing',
  '文件还没准备好': 'server.fileNotReady',
  '问题无效，请检查后重试': 'server.invalidQuestion',
  '请先登录': 'server.needLogin',
  '跨站请求被拒绝': 'server.crossSite',
  '操作太频繁，请一分钟后再试': 'server.tooFrequent',
  '尝试次数过多，请几分钟后再试': 'server.tooManyAttempts',
  '邮箱或密码不正确': 'server.badCredentials',
  '邮箱格式不正确': 'server.badEmail',
  '重置链接无效或已过期，请重新申请': 'server.resetExpired',
  '这个邮箱已经注册过了': 'server.emailTaken',
  '密码至少 8 位': 'error.passwordTooShort',
  '密码太长，最多 72 个字节': 'server.passwordTooLong',
  '请提供视频链接或字幕文本': 'server.needSource',
  '请提供视频链接或提纲内容': 'server.needOutline',
  '问题不能为空': 'server.emptyQuestion',
  '还没有可问答的内容，请提供视频链接或粘贴资料': 'server.noQaContext',
  '处理中断，请稍后重试': 'server.interrupted',
  '这条公开视频没有可用字幕，暂时无法总结': 'server.noSubtitle',
  '暂时无法读取字幕，请稍后再试': 'server.subtitleUnavailable',
  '当前总结较多，请稍后再试': 'server.summaryBusy',
  '还没有配置总结服务': 'server.summaryNotConfigured',
  '总结服务的密钥无效': 'server.summaryKeyInvalid',
  '总结服务繁忙，请稍后再试': 'server.modelBusy',
  '总结失败，请重试': 'error.summaryFailed',
  '总结没有生成，请重试': 'error.summaryFailed',
  '回答没有生成，请重试': 'error.answerFailed',
  '没有可用的提纲内容，请粘贴文字后再试': 'server.noOutline',
  '你已经是会员了': 'server.alreadyMember',
  '支付暂时不可用': 'error.payUnavailable',
  '支付暂时不可用，请稍后再试': 'error.payUnavailable',
  '订单不存在': 'server.orderMissing',
  '本机未检测到 ffmpeg。画面和声音是分开的清晰度需要它才能合成一个文件，仅音频可以先保存。':
    'server.ffmpegHintMux',
  '本机未检测到 ffmpeg，暂时只能保存已经包含声音的单文件。': 'server.ffmpegHintSingle',
  '原文件': 'server.originalLabel',
  '仅音频': 'server.audioOnlyLabel',
  '未命名视频': 'server.untitledVideo',
  '视频': 'server.videoLabel',
}

// 带变量的提示用正则匹配
const SERVER_PATTERNS = [
  {
    pattern: /^文件超过约\s*(\S+?)，请换较低清晰度$/,
    key: 'server.fileTooLarge',
    params: (found) => ({ size: found[1] }),
  },
  {
    pattern: /^今天的\s*(\d+)\s*次免费下载已用完/,
    key: 'server.quotaExhausted',
    params: (found) => ({ count: found[1] }),
  },
]

// SSE 进度事件只认 stage，文案由前端自己组织，避免直接展示后端中文
const STAGE_KEYS = {
  fetching_subtitles: 'stage.fetching',
  processing_subtitles: 'stage.processing',
  summarizing: 'stage.summarizing',
  building_mindmap: 'stage.building',
  thinking: 'stage.thinking',
}

export function stageMessage(stage, fallback = '') {
  return STAGE_KEYS[stage] || fallback
}

/**
 * 统一渲染提示文本，支持三种入参：
 * 1. 语言包 key，如 'error.parseFailed'
 * 2. 服务端返回的中文原文，命中映射表时翻译
 * 3. 任意原样展示的文本（如视频标题）
 */
export function renderMessage(value) {
  if (!value) return ''
  if (typeof value === 'object') {
    if (value.key) return i18n.global.t(value.key, value.params || {})
    return value.text || ''
  }
  const text = String(value)
  if (i18n.global.te(text)) return i18n.global.t(text)
  const mapped = SERVER_MESSAGES[text]
  if (mapped) return i18n.global.t(mapped)
  for (const rule of SERVER_PATTERNS) {
    const found = text.match(rule.pattern)
    if (found) return i18n.global.t(rule.key, rule.params(found))
  }
  return text
}
