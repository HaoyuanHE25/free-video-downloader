function parseBlock(raw) {
  let event = 'message'
  const data = []
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const split = line.indexOf(':')
    const field = split === -1 ? line : line.slice(0, split)
    const value = split === -1 ? '' : line.slice(split + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (!data.length) return null
  const text = data.join('\n')
  try {
    return { event, data: JSON.parse(text) }
  } catch {
    return { event, data: { text } }
  }
}

async function requestError(response) {
  const body = await response.text()
  try {
    const data = JSON.parse(body)
    if (typeof data.detail === 'string') return data.detail
  } catch {
    // 不是 JSON 就走兜底文案
  }
  return '请求没有完成，请重试'
}

async function streamRequest(path, payload, onEvent, signal) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) throw new Error(await requestError(response))
  if (!response.body) throw new Error('当前浏览器不支持流式响应')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let failure = null
  const dispatch = (block) => {
    if (!block || failure) return
    try {
      onEvent(block)
    } catch (err) {
      // 业务错误帧：先记住错误，继续读完流，避免 cancel 触发 ERR_ABORTED。
      failure = err
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')
      let cut = buffer.indexOf('\n\n')
      while (cut !== -1) {
        dispatch(parseBlock(buffer.slice(0, cut)))
        buffer = buffer.slice(cut + 2)
        cut = buffer.indexOf('\n\n')
      }
    }
    dispatch(parseBlock(buffer))
    if (failure) throw failure
  } finally {
    reader.releaseLock()
  }
}

export function streamSummary(url, onEvent, signal) {
  return streamRequest('/api/summary/stream', { url }, onEvent, signal)
}

export function streamSubtitles(payload, onEvent, signal) {
  return streamRequest('/api/subtitles/stream', payload, onEvent, signal)
}

export function streamMindmap(payload, onEvent, signal) {
  return streamRequest('/api/mindmap/stream', payload, onEvent, signal)
}

export function streamAsk(payload, onEvent, signal) {
  return streamRequest('/api/summary/ask/stream', payload, onEvent, signal)
}
