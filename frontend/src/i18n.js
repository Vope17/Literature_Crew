import { ref } from 'vue'
import zhTW from './locales/zh-TW.json'

export const locale = ref('en')
const storageKey = 'literature-locale'
export function setLocale(value, persist = true) {
  locale.value = value === 'zh-TW' ? 'zh-TW' : 'en'
  if (typeof document !== 'undefined') document.documentElement.lang = locale.value
  if (persist) {
    try { localStorage.setItem(storageKey, locale.value) } catch { /* Works without storage. */ }
  }
}
export function loadLocale() {
  let saved
  try { saved = localStorage.getItem(storageKey) } catch { /* Default to English. */ }
  setLocale(saved, false)
}
const templates = Object.entries(zhTW).filter(([key]) => key.includes('{')).map(([key, value]) => {
  const names = []
  const source = key.split(/(\{\w+\})/).map(part => {
    if (/^\{\w+\}$/.test(part)) { names.push(part.slice(1, -1)); return '(.+?)' }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }).join('')
  return { pattern: new RegExp(`^${source}$`, 's'), names, value }
})
export function t(message, params = {}) {
  const original = String(message ?? '')
  let text = original
  if (locale.value === 'zh-TW') {
    text = Object.hasOwn(zhTW, original) ? zhTW[original] : original
    if (text === original && !Object.keys(params).length) {
      for (const entry of templates) {
        const match = original.match(entry.pattern)
        if (!match) continue
        text = entry.value
        params = Object.fromEntries(entry.names.map((name, index) => [name, match[index + 1]]))
        break
      }
    }
  }
  return text.replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match)
}
