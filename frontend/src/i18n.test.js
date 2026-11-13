import { afterEach, expect, it, vi } from 'vitest'
import { locale, t, setLocale, loadLocale } from './i18n'

afterEach(() => { setLocale('en', false); localStorage.clear(); vi.unstubAllGlobals() })
it('persists locale and updates document language without translating user content', () => {
  setLocale('zh-TW')
  expect(t('Search papers')).toBe('搜尋論文')
  expect(t('Linux internals')).toBe('Linux internals')
  expect(t('__proto__')).toBe('__proto__')
  expect(document.documentElement.lang).toBe('zh-TW')
  setLocale('en', false)
  loadLocale()
  expect(locale.value).toBe('zh-TW')
  expect(t('Papers for “{topic}”', { topic: '<script>test</script>' })).toBe('「<script>test</script>」的論文')
})
it('translates dynamic server progress and works without local storage', () => {
  vi.stubGlobal('localStorage', { getItem: () => { throw Error('denied') }, setItem: () => { throw Error('denied') }, clear: () => {} })
  loadLocale()
  setLocale('zh-TW')
  expect(t('Reading P1: pages 1–4/12, batch 1 (text + images)…')).toContain('第 1–4/12 頁')
  expect(t('Years must be whole numbers between 1900 and 2027.')).toContain('2027')
})
