async function request(path, options = {}) {
  const response = await fetch(path, {
    // 登录态走 HttpOnly Cookie，必须带上同源凭证；登录/会员接口不允许被缓存
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const text = await response.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: 'error.generic' }
    }
  }
  if (!response.ok) {
    const detail = data && data.detail
    const message = typeof detail === 'string' ? detail : 'error.generic'
    throw new Error(message)
  }
  return data
}

export function parseVideo(url) {
  return request('/api/parse', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
}

export function startDownload(url, formatId) {
  return request('/api/download', {
    method: 'POST',
    body: JSON.stringify({ url, format_id: formatId }),
  })
}

export function getJob(id) {
  return request(`/api/jobs/${id}`)
}

export function fileUrl(id) {
  return `/api/jobs/${id}/file`
}

export function getMe() {
  return request('/api/me')
}

export function registerAccount(email, password) {
  return request('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function loginWithPassword(email, password) {
  return request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function requestPasswordReset(email) {
  return request('/api/auth/request-reset', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function resetPassword(token, password) {
  return request('/api/auth/reset', {
    method: 'POST',
    body: JSON.stringify({ token, password }),
  })
}

export function logout() {
  return request('/api/auth/logout', { method: 'POST' })
}

export function startCheckout() {
  return request('/api/billing/checkout', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function getOrder(sessionId) {
  return request(`/api/billing/orders/${encodeURIComponent(sessionId)}`)
}
