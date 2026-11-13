import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ChatGPTLogin from './ChatGPTLogin.vue'

const reply = (data: unknown, ok = true) => Promise.resolve({ ok, json: async () => data })
const disconnected = { status: 'disconnected', connected: false }
const pending = { status: 'pending', connected: false, user_code: 'ABCD-1234', verification_url: 'https://auth.openai.com/codex/device' }
let wrapper: VueWrapper | undefined
const clickButton = (text: string) => {
  const found = wrapper?.findAll('button').find(item => item.text() === text)
  if (!found) throw new Error(`No button "${text}"`)
  return found.trigger('click')
}
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('shows the official authorization page and code, then detects a completed login', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn()
    .mockImplementationOnce(() => reply(disconnected))
    .mockImplementationOnce(() => reply(pending))
    .mockImplementationOnce(() => reply({ status: 'connected', connected: true, plan: 'plus' }))
  vi.stubGlobal('fetch', fetch)
  wrapper = mount(ChatGPTLogin)
  await flushPromises()
  await wrapper.get('[data-testid="chatgpt-connect"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="device-code"]').text()).toBe('ABCD-1234')
  expect(wrapper.get('.auth-link').attributes('href')).toBe('https://auth.openai.com/codex/device')
  expect(fetch.mock.calls[1]?.[0]).toBe('/api/auth/chatgpt/start')
  expect(fetch.mock.calls[1]?.[1]?.body).toBe('{}')
  await vi.advanceTimersByTimeAsync(2000)
  await flushPromises()
  expect(wrapper.get('[data-testid="chatgpt-connected"]').text()).toContain('plus')
  expect(wrapper.find('[data-testid="device-code"]').exists()).toBe(false)
  expect(wrapper.emitted('connected')?.at(-1)).toEqual([true])
})

it('cancels a pending login and removes its code', async () => {
  const fetch = vi.fn()
    .mockImplementationOnce(() => reply(pending))
    .mockImplementationOnce(() => reply(disconnected))
  vi.stubGlobal('fetch', fetch)
  wrapper = mount(ChatGPTLogin)
  await flushPromises()
  await clickButton('Cancel sign-in')
  await flushPromises()
  expect(fetch.mock.calls[1]?.[0]).toBe('/api/auth/chatgpt/cancel')
  expect(wrapper.find('[data-testid="device-code"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="chatgpt-connect"]').exists()).toBe(true)
})

it('keeps failed status checks recoverable and reconnects after expiry', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockRejectedValueOnce(new Error('Connection lost'))
    .mockImplementationOnce(() => reply({ status: 'expired', connected: false, message: 'Sign-in expired.' })))
  wrapper = mount(ChatGPTLogin)
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Connection lost')
  await clickButton('Retry status check')
  await flushPromises()
  expect(wrapper.text()).toContain('Sign-in expired.')
  expect((wrapper.get('[data-testid="chatgpt-connect"]').element as HTMLButtonElement).disabled).toBe(false)
})
