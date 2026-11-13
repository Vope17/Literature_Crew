import { ref } from 'vue'
import zhTW from './locales/zh-TW.json'

export type Locale = 'en' | 'zh-TW'
export type Params = Record<string, string | number>

const messages: Record<string, string> = zhTW
export const locale = ref<Locale>('en')
const storageKey = 'literature-locale'

export function setLocale(value: string | null | undefined, persist = true): void {
  locale.value = value === 'zh-TW' ? 'zh-TW' : 'en'
  if (typeof document !== 'undefined') document.documentElement.lang = locale.value
  if (persist) {
    try { localStorage.setItem(storageKey, locale.value) } catch { /* Works without storage. */ }
  }
}

export function loadLocale(): void {
  let saved: string | null = null
  try { saved = localStorage.getItem(storageKey) } catch { /* Default to English. */ }
  setLocale(saved, false)
}

// Messages with {placeholders} also translate server text that arrives pre-formatted.
const templates = Object.entries(messages).filter(([key]) => key.includes('{')).map(([key, value]) => {
  const names: string[] = []
  const source = key.split(/(\{\w+\})/).map(part => {
    if (/^\{\w+\}$/.test(part)) { names.push(part.slice(1, -1)); return '(.+?)' }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }).join('')
  return { pattern: new RegExp(`^${source}$`, 's'), names, value }
})

export function t(message: unknown, params: Params = {}): string {
  const original = String(message ?? '')
  let text = original
  if (locale.value === 'zh-TW') {
    text = Object.hasOwn(messages, original) ? messages[original] : original
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
  return text.replace(/\{(\w+)\}/g, (match, name: string) => String(params[name] ?? match))
}
