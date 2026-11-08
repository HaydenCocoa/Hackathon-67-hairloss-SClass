// Relative URLs use Vite's proxy in development and FastAPI in a built app.
export async function getJson(path) {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(12000),
  })
  const body = await response.json()
  if (!response.ok && !(path === '/api/health/database' && response.status === 503 && body.status)) {
    throw new Error('The server could not complete this request.')
  }
  return body
}
