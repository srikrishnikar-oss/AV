const RETRY_COUNT = 3
const RETRY_DELAY_MS = 1000

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

export async function requestJson(url, options = {}) {
  let lastError = null

  for (let attempt = 0; attempt < RETRY_COUNT; attempt += 1) {
    try {
      const response = await fetch(url, options)
      if (!response.ok) {
        let detail = ''
        try {
          const body = await response.json()
          detail = body?.detail ?? ''
        } catch {
          detail = ''
        }
        const error = new Error(detail || `Request failed with status ${response.status}`)
        error.status = response.status
        error.detail = detail
        throw error
      }
      return await response.json()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error
      }
      lastError = error
      if (attempt < RETRY_COUNT - 1) {
        await delay(RETRY_DELAY_MS)
      }
    }
  }

  throw lastError ?? new Error('Request failed.')
}
