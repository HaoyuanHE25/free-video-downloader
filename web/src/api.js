async function request(path, options = {}) {
  const response = await fetch(path, {
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
      data = { detail: '请求没有完成，请重试' }
    }
  }
  if (!response.ok) {
    const detail = data && data.detail
    const message = typeof detail === 'string' ? detail : '请求没有完成，请重试'
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
