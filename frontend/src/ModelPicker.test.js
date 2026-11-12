import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ModelPicker from './ModelPicker.vue'

let wrapper
const response = (data, ok = true) => Promise.resolve({ ok, json: async () => data })
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

it('loads models after connection and emits the selected provider ID', async () => {
  const fetch = vi.fn(() => response({ models: [{ id: 'openai/chosen', name: 'Chosen' }] }))
  vi.stubGlobal('fetch', fetch)
  wrapper = mount(ModelPicker, { props: { enabled: false } })
  expect(fetch).not.toHaveBeenCalled()
  await wrapper.setProps({ enabled: true })
  await flushPromises()
  await wrapper.get('select').setValue('openai/chosen')
  expect(wrapper.emitted('update:modelValue').at(-1)).toEqual(['openai/chosen'])
  await wrapper.setProps({ enabled: false })
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([''])
})

it('shows catalog failures and allows refresh without losing a valid choice', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => response({ detail: 'Sign in again' }, false))
    .mockImplementationOnce(() => response({ models: [{ id: 'chosen', name: 'Chosen' }] })))
  wrapper = mount(ModelPicker, { props: { enabled: true } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('Sign in again')
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.get('select').text()).toContain('Chosen')
})
