export function formatBytes(value) {
  if (!value) return '大小未知'
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  const mb = value / (1024 * 1024)
  return `${mb >= 10 ? mb.toFixed(0) : mb.toFixed(1)} MB`
}

export function formatDuration(seconds) {
  if (seconds == null) return ''
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remain = total % 60
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remain).padStart(2, '0')}`
  }
  return `${minutes}:${String(remain).padStart(2, '0')}`
}
