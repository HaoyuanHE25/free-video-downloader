import { reactive } from 'vue'
import { getMe } from './api.js'

// 本地只缓存"展示用"的登录态，真正的身份与会员资格始终以服务端 /api/me 为准。
// 这样刷新、关闭浏览器重开都能立刻还原界面，同时缓存被篡改也无法通过任何接口校验。
const CACHE_KEY = 'sx.session.v1'
const CHANNEL_NAME = 'sx-session'
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000
const REVALIDATE_INTERVAL_MS = 60 * 1000

export const session = reactive({
  ready: false,
  user: null,
  member: false,
  limits: null,
  price: null,
  // 当前值来自本地缓存、还没被服务端确认
  stale: false,
  syncing: false,
})

export const authPanel = reactive({ open: false })
export const memberPanel = reactive({ open: false })

export function openAuth() {
  authPanel.open = true
}

export function closeAuth() {
  authPanel.open = false
}

function canUseStorage() {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage)
  } catch {
    return false
  }
}

function readCache() {
  if (!canUseStorage()) return null
  try {
    const raw = window.localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    if (!data || typeof data !== 'object') return null
    if (typeof data.updatedAt !== 'number') return null
    if (Date.now() - data.updatedAt > CACHE_TTL_MS) return null
    return data
  } catch {
    return null
  }
}

function writeCache() {
  if (!canUseStorage()) return
  try {
    window.localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        user: session.user,
        member: session.member,
        limits: session.limits,
        price: session.price,
        updatedAt: Date.now(),
      }),
    )
  } catch {
    // 存储被禁用或写满时忽略，不影响在线校验
  }
}

function clearCache() {
  if (!canUseStorage()) return
  try {
    window.localStorage.removeItem(CACHE_KEY)
  } catch {
    // 忽略
  }
}

function snapshot() {
  return JSON.stringify({
    user: session.user,
    member: session.member,
    limits: session.limits,
    price: session.price,
  })
}

function applyCache(cache) {
  session.user = cache.user || null
  session.member = Boolean(cache.member)
  session.limits = cache.limits || null
  session.price = cache.price || null
  session.stale = true
  session.ready = true
}

function applyServer(data) {
  const before = snapshot()
  session.user = data.authenticated ? data.user : null
  session.member = Boolean(data.member)
  session.limits = data.limits || null
  session.price = data.price || null
  session.stale = false
  session.ready = true
  lastSyncAt = Date.now()

  const changed = snapshot() !== before
  if (!session.user) {
    clearCache()
  } else if (changed || !readCache()) {
    writeCache()
  }
  if (changed) broadcast()
}

let channel = null
let channelReady = false

function getChannel() {
  if (channelReady) return channel
  channelReady = true
  if (typeof window === 'undefined' || typeof window.BroadcastChannel !== 'function') {
    channel = null
    return channel
  }
  try {
    channel = new window.BroadcastChannel(CHANNEL_NAME)
    channel.onmessage = (event) => {
      if (event && event.data && event.data.type === 'session') {
        refreshSession({ force: true })
      }
    }
  } catch {
    channel = null
  }
  return channel
}

function broadcast() {
  const bus = getChannel()
  if (!bus) return
  try {
    bus.postMessage({ type: 'session', at: Date.now() })
  } catch {
    // 忽略
  }
}

let inflight = null
let lastSyncAt = 0

/**
 * 以服务端为准刷新登录态：
 * - 成功：覆盖本地状态并同步缓存/其他标签页
 * - 失败（网络异常）：保留缓存，标记 stale，不把用户"踢下线"
 */
export function refreshSession({ force = false } = {}) {
  if (inflight) return inflight
  if (!force && lastSyncAt && Date.now() - lastSyncAt < 1000) return Promise.resolve()
  session.syncing = true
  inflight = getMe()
    .then((data) => {
      applyServer(data)
    })
    .catch(() => {
      // 服务端暂时不可用：保留上次确认过的状态，避免刷新页面就丢会员
      session.ready = true
    })
    .finally(() => {
      inflight = null
      session.syncing = false
    })
  return inflight
}

function bindCrossTab() {
  if (typeof window === 'undefined') return
  window.addEventListener('storage', (event) => {
    if (event.key === CACHE_KEY) refreshSession({ force: true })
  })
  const revalidate = () => {
    if (Date.now() - lastSyncAt > REVALIDATE_INTERVAL_MS) refreshSession({ force: true })
  }
  window.addEventListener('focus', revalidate)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') revalidate()
  })
  getChannel()
}

const cached = readCache()
if (cached) applyCache(cached)
bindCrossTab()
