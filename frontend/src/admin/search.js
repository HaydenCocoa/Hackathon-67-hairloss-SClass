// Admin list search: case-insensitive; every word typed must appear in one of the values.
export function matchesSearch(term, ...values) {
  const words = String(term ?? '').toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const text = values.filter(value => value != null).join(' ').toLowerCase()
  return words.every(word => text.includes(word))
}

// Simple shape check before sending; Supabase Auth makes the final decision.
export const looksLikeEmail = value => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(value ?? '').trim())
