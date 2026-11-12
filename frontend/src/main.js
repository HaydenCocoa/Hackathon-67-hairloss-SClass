import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

// If any API call reports that the login has expired (HTTP 401), go to the login
// page and come back afterwards. This covers pages that do their own fetching
// (student and lecturer pages) without changing them.
const nativeFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const response = await nativeFetch(input, init)
  try {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin)
    const isAppApi = url.origin === window.location.origin && url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/auth/')
    if (response.status === 401 && isAppApi && window.location.pathname !== '/login') {
      window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`)
    }
  } catch {
    // Unparseable URL: leave the response to the caller.
  }
  return response
}

createApp(App).mount('#app')
