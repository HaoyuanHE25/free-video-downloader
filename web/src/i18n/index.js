import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

// 支持的语言。short 用于切换按钮，htmlLang 同步到 <html lang>。
export const LOCALES = [
  { code: 'zh-CN', short: '中文', name: '简体中文', htmlLang: 'zh-CN' },
  { code: 'en', short: 'EN', name: 'English', htmlLang: 'en' },
]

export const DEFAULT_LOCALE = 'zh-CN'

const STORAGE_KEY = 'sx.locale.v1'
const SUPPORTED = LOCALES.map((item) => item.code)

function readStored() {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved && SUPPORTED.includes(saved)) return saved
  } catch {
    // 隐私模式或存储被禁用时忽略，回落到浏览器语言
  }
  return ''
}

// 优先级：本地缓存 → 浏览器语言 → 默认中文
function detectLocale() {
  if (typeof window === 'undefined') return DEFAULT_LOCALE
  const stored = readStored()
  if (stored) return stored
  const languages = window.navigator.languages || [window.navigator.language]
  for (const item of languages) {
    const tag = String(item || '').toLowerCase()
    if (tag.startsWith('zh')) return 'zh-CN'
    if (tag.startsWith('en')) return 'en'
  }
  return DEFAULT_LOCALE
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { 'zh-CN': zhCN, en },
  // 缺词时直接用兜底语言，不往控制台刷警告
  missingWarn: false,
  fallbackWarn: false,
})

// 同步 <html lang>、标题和描述，便于搜索引擎与读屏软件识别当前语言
function applyDocument(locale) {
  if (typeof document === 'undefined') return
  const target = LOCALES.find((item) => item.code === locale) || LOCALES[0]
  document.documentElement.lang = target.htmlLang
  document.title = i18n.global.t('meta.title')
  const description = document.querySelector('meta[name="description"]')
  if (description) description.setAttribute('content', i18n.global.t('meta.description'))
}

export function setLocale(code) {
  const next = SUPPORTED.includes(code) ? code : DEFAULT_LOCALE
  i18n.global.locale.value = next
  try {
    window.localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 存储不可用时只在本次会话生效
  }
  applyDocument(next)
  return next
}

export function currentLocale() {
  return i18n.global.locale.value
}

applyDocument(i18n.global.locale.value)
