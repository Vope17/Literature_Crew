import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import App from './App.vue'

const paper = {
  title: 'Graph paper', authors: ['Ada'], year: 2025,
  url: 'https://arxiv.org/abs/2501.00001', abstract: 'Abstract',
}
const config = {
  model: 'openai/example', has_api_key: true, max_papers: 5,
  search_areas: [{ value: 'all', label: 'All subjects' }, { value: 'computer_science', label: 'Computer science' }],
}
const respond = (data, ok = true, headers = {}) => Promise.resolve({
  ok, json: () => Promise.resolve(data), headers: { get: name => headers[name] },
})
let wrapper
beforeEach(() => {
  const values = new Map()
  vi.stubGlobal('localStorage', {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    clear: () => values.clear(),
  })
})
afterEach(() => { wrapper?.unmount(); window.localStorage.clear(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('searches, selects papers, generates a review, and shows coverage', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
    .mockImplementationOnce(() => respond({ id: 'review-1', status: 'queued' }))
    .mockImplementationOnce(() => respond({
      id: 'review-1', status: 'completed',
      review: '# Review\nA finding [P1].\n<script>alert(1)</script>',
      evidence: [{ id: 'P1', title: paper.title, coverage: 'abstract only' }],
    }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('[data-testid="configured-model"]').text()).toBe('openai/example')
  expect(wrapper.find('input[type="password"]').exists()).toBe(false)
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('input[type="checkbox"]').element.checked).toBe(true)
  await wrapper.findAll('button').find(b => b.text() === 'Generate review').trigger('click')
  await flushPromises()
  const submitted = JSON.parse(fetchMock.mock.calls[2][1].body)
  expect(submitted).not.toHaveProperty('model')
  expect(submitted).not.toHaveProperty('api_key')
  expect(submitted.topic).toBe('graphs')
  expect(submitted.papers).toEqual([paper])
  expect(wrapper.get('.markdown h1').text()).toBe('Review')
  expect(wrapper.find('.markdown script').exists()).toBe(false)
  expect(wrapper.get('.warning').text()).toContain('abstract only')
  expect(wrapper.findAll('.downloads button')).toHaveLength(2)
})

it('shows API errors and permits retry', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ detail: 'arXiv unavailable' }, false)))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('arXiv unavailable')
  expect(wrapper.get('button[type="submit"]').element.disabled).toBe(false)
})

it('limits selection to five papers', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: Array.from({ length: 6 }, (_, i) => ({ ...paper, url: `${paper.url}${i}` })) })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const boxes = wrapper.findAll('input[type="checkbox"]')
  await boxes[3].setValue(true)
  await boxes[4].setValue(true)
  expect(boxes[5].element.disabled).toBe(true)
})

it('honors the search retry countdown', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ detail: 'arXiv is rate-limiting requests.' }, false, { 'Retry-After': '60' })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('button[type="submit"]').text()).toBe('Retry in 60s')
  expect(wrapper.get('button[type="submit"]').element.disabled).toBe(true)
  vi.advanceTimersByTime(60_000)
  await flushPromises()
  expect(wrapper.get('button[type="submit"]').element.disabled).toBe(false)
})

it('labels fallback results and permits review generation', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({
      papers: [paper], source: 'Semantic Scholar',
      notice: 'arXiv is unavailable. Showing results from Semantic Scholar.',
    })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('.results .warning').text()).toContain('Semantic Scholar')
  expect(wrapper.get('.results .section-heading').text()).toContain('results from Semantic Scholar')
  expect(wrapper.findAll('button').find(b => b.text() === 'Generate review').element.disabled).toBe(false)
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})

it('allows searching but disables generation when the server has no key', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond({ ...config, has_api_key: false }))
    .mockImplementationOnce(() => respond({ papers: [paper] })))
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('.settings .warning').text()).toContain('backend/.env')
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.findAll('.paper')).toHaveLength(1)
  expect(wrapper.findAll('button').find(b => b.text() === 'Generate review').element.disabled).toBe(true)
})

it('does not offer or request available models', async () => {
  const fetchMock = vi.fn(() => respond(config))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.text()).not.toContain('Show available models')
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/config'])
})

it('submits filters and preserves the applied summary until the next search', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('[data-testid="area-filter"]').setValue('computer_science')
  await wrapper.get('[data-testid="year-from"]').setValue('2020')
  await wrapper.get('[data-testid="year-to"]').setValue('2025')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    topic: 'graphs', limit: 5, area: 'computer_science', year_from: 2020, year_to: 2025,
  })
  expect(wrapper.get('[data-testid="applied-filters"]').text()).toBe('Computer science · 2020–2025')
  await wrapper.findAll('button').find(button => button.text() === 'Reset filters').trigger('click')
  expect(wrapper.get('[data-testid="area-filter"]').element.value).toBe('all')
  expect(wrapper.get('[data-testid="year-from"]').element.value).toBe('')
  expect(wrapper.get('[data-testid="applied-filters"]').text()).toBe('Computer science · 2020–2025')
})

it('rejects reversed year ranges before making a search request', async () => {
  const fetchMock = vi.fn(() => respond(config))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('[data-testid="year-from"]').setValue('2025')
  await wrapper.get('[data-testid="year-to"]').setValue('2020')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('[role="alert"]').text()).toContain('Start year')
  expect(wrapper.get('button[type="submit"]').element.disabled).toBe(true)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('polls review progress while allowing another search, then shows the saved review', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
    .mockImplementationOnce(() => respond({ id: 'job', status: 'queued' }))
    .mockImplementationOnce(() => respond({
      id: 'job', topic: 'graphs', status: 'running', progress: 'Reading paper 1/1',
      created_at: new Date().toISOString(),
    }))
    .mockImplementationOnce(() => respond({ papers: [] }))
    .mockImplementationOnce(() => respond({
      id: 'job', topic: 'graphs', status: 'completed', review: '# Saved review', evidence: [],
    }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Generate review').trigger('click')
  await flushPromises()
  expect(wrapper.get('.review-progress').text()).toContain('Reading paper 1/1')
  expect(wrapper.get('button[type="submit"]').element.disabled).toBe(false)
  expect(wrapper.get('input[placeholder^="e.g."]').element.disabled).toBe(false)
  expect(window.localStorage.getItem('literature-active-review')).toBe('job')
  await wrapper.get('input[placeholder^="e.g."]').setValue('different topic')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  vi.advanceTimersByTime(2000)
  await flushPromises()
  expect(wrapper.find('.review-progress').exists()).toBe(false)
  expect(wrapper.get('.report h2').text()).toBe('Review: graphs')
  expect(wrapper.get('.markdown h1').text()).toBe('Saved review')
  expect(window.localStorage.getItem('literature-active-review')).toBeNull()
  expect(fetchMock.mock.calls.at(-1)[0]).toBe('/api/reviews/job')
})

it('reconnects to an active review after refresh', async () => {
  window.localStorage.setItem('literature-active-review', 'saved-job')
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({
      id: 'saved-job', topic: 'graphs', status: 'completed', review: '# Restored review', evidence: [],
    })))
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('.markdown h1').text()).toBe('Restored review')
  expect(window.localStorage.getItem('literature-active-review')).toBeNull()
})

it('shows failed jobs and enables generation again', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
    .mockImplementationOnce(() => respond({ id: 'job', status: 'queued' }))
    .mockImplementationOnce(() => respond({ id: 'job', status: 'failed', error: 'Review failed. Please try again.' })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const generate = wrapper.findAll('button').find(b => b.text() === 'Generate review')
  await generate.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Review failed')
  expect(generate.element.disabled).toBe(false)
  expect(window.localStorage.getItem('literature-active-review')).toBeNull()
})

it('keeps a job recoverable after a polling connection error', async () => {
  window.localStorage.setItem('literature-active-review', 'job')
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockRejectedValueOnce(new Error('Connection lost'))
    .mockImplementationOnce(() => respond({ id: 'job', status: 'completed', review: '# Recovered', evidence: [] }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(window.localStorage.getItem('literature-active-review')).toBe('job')
  await wrapper.findAll('button').find(b => b.text() === 'Retry status check').trigger('click')
  await flushPromises()
  expect(wrapper.get('.markdown h1').text()).toBe('Recovered')
})

it('expands history and reopens a review and its saved PDF without regenerating', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ items: [{
      id: 'old-review', kind: 'review', topic: 'graphs', status: 'completed', paper_count: 1,
      created_at: '2026-01-01T00:00:00Z',
    }], has_more: false }))
    .mockImplementationOnce(() => respond({
      id: 'old-review', kind: 'review', topic: 'graphs', status: 'completed', papers: [paper],
      review: '# Historical review', evidence: [{ id: 'P1', title: paper.title, coverage: 'full PDF', stored_pdf_url: '/api/pdfs/pdf1' }],
    }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.find('#history-content').exists()).toBe(false)
  await wrapper.get('[data-testid="history-toggle"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="history-toggle"]').attributes('aria-expanded')).toBe('true')
  await wrapper.findAll('button').find(b => b.text() === 'Open result').trigger('click')
  await flushPromises()
  expect(wrapper.get('.markdown h1').text()).toBe('Historical review')
  expect(wrapper.get('.saved-pdfs a').attributes('href')).toBe('/api/pdfs/pdf1')
  expect(fetchMock.mock.calls.every(call => !call[1]?.method)).toBe(true)
  await wrapper.get('[data-testid="history-toggle"]').trigger('click')
  expect(wrapper.find('#history-content').exists()).toBe(false)
})

it('restores saved search filters and papers from history', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ items: [{
      id: 'old-search', kind: 'search', topic: 'graphs', status: 'completed', paper_count: 1,
      created_at: '2026-01-01T00:00:00Z',
    }], has_more: false }))
    .mockImplementationOnce(() => respond({
      id: 'old-search', kind: 'search', topic: 'graphs', papers: [paper], source: 'arXiv',
      filters: { area: 'computer_science', year_from: 2020, year_to: 2025 },
    })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('[data-testid="history-toggle"]').trigger('click')
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Open result').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="area-filter"]').element.value).toBe('computer_science')
  expect(wrapper.get('[data-testid="applied-filters"]').text()).toBe('Computer science · 2020–2025')
  expect(wrapper.findAll('.paper')).toHaveLength(1)
})
