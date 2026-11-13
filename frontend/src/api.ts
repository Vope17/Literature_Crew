export class ApiError extends Error {
  status = 0
  retryAfter = 0
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

const timeouts: Record<string, number> = { search: 310_000, 'ai/connection': 60_000 }

/** POST when a body is given, otherwise GET. Failures carry the HTTP status and Retry-After seconds. */
export async function request<T>(path: string, body?: unknown): Promise<T> {
  const signal = AbortSignal.timeout(timeouts[path] ?? 15_000)
  let response: Response
  try {
    response = await fetch(`/api/${path}`, body ? {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    } : { signal, cache: 'no-store' })
  } catch {
    throw new Error('Cannot reach the server. Check that the Python backend is running.')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const failure = new ApiError(typeof data.detail === 'string' ? data.detail : 'Request failed. Please retry.')
    failure.status = response.status
    failure.retryAfter = Number(response.headers?.get('Retry-After')) || 0
    throw failure
  }
  return data as T
}
