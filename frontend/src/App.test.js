import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { config as testConfig, flushPromises, mount } from '@vue/test-utils'
import App from './App.vue'

const paper = {
  title: 'Graph paper', authors: ['Ada'], year: 2025,
  url: 'https://arxiv.org/abs/2501.00001', abstract: 'Abstract',
}
const config = {
  model: 'openai/example', has_api_key: true, api_verified: true, max_papers: 5,
  search_areas: [{ value: 'all', label: 'All subjects' }, { value: 'computer_science', label: 'Computer science' }],
}
const respond = (data, ok = true, headers = {}) => Promise.resolve({
  ok, json: () => Promise.resolve(data), headers: { get: name => headers[name] },
})
let wrapper
beforeEach(() => {
  testConfig.global.stubs.ModelPicker = true
  const values = new Map()
  vi.stubGlobal('localStorage', {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    clear: () => values.clear(),
  })
})
afterEach(() => { wrapper?.unmount(); delete testConfig.global.stubs.ModelPicker; window.localStorage.clear(); vi.unstubAllGlobals(); vi.useRealTimers() })

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
  expect(wrapper.find('input[type="password"]').exists()).toBe(true)
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
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
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('arXiv unavailable')
  expect(wrapper.get('.search button[type="submit"]').element.disabled).toBe(false)
})

it('limits selection to five papers', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: Array.from({ length: 6 }, (_, i) => ({ ...paper, url: `${paper.url}${i}` })) })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
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
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  expect(wrapper.get('.search button[type="submit"]').text()).toBe('Retry in 60s')
  expect(wrapper.get('.search button[type="submit"]').element.disabled).toBe(true)
  vi.advanceTimersByTime(60_000)
  await flushPromises()
  expect(wrapper.get('.search button[type="submit"]').element.disabled).toBe(false)
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
  await wrapper.get('form.search').trigger('submit')
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
  expect(wrapper.find('[data-testid="api-key"]').exists()).toBe(true)
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  expect(wrapper.findAll('.paper')).toHaveLength(1)
  expect(wrapper.findAll('button').find(b => b.text() === 'Generate review').element.disabled).toBe(true)
})

it('submits the chosen model with the report request', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
    .mockImplementationOnce(() => respond({ id: 'chosen-job', status: 'queued' }))
    .mockImplementationOnce(() => respond({ id: 'chosen-job', status: 'completed', review: '# Chosen model', evidence: [] }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  wrapper.findComponent({ name: 'ModelPicker' }).vm.$emit('update:modelValue', 'openai/chosen')
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  await wrapper.get('.selection-bar button:last-child').trigger('click')
  await flushPromises()
  expect(JSON.parse(fetchMock.mock.calls[2][1].body).model).toBe('openai/chosen')
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
  await wrapper.get('form.search').trigger('submit')
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
  await wrapper.get('form.search').trigger('submit')
  expect(wrapper.get('[role="alert"]').text()).toContain('Start year')
  expect(wrapper.get('.search button[type="submit"]').element.disabled).toBe(true)
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
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  await wrapper.findAll('button').find(b => b.text() === 'Generate review').trigger('click')
  await flushPromises()
  expect(wrapper.get('.review-progress').text()).toContain('Reading paper 1/1')
  expect(wrapper.get('.search button[type="submit"]').element.disabled).toBe(false)
  expect(wrapper.get('input[placeholder^="e.g."]').element.disabled).toBe(false)
  expect(window.localStorage.getItem('literature-active-review')).toBe('job')
  await wrapper.get('input[placeholder^="e.g."]').setValue('different topic')
  await wrapper.get('form.search').trigger('submit')
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
  await wrapper.get('form.search').trigger('submit')
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
  await wrapper.get('.history-item').trigger('click')
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
  await wrapper.get('.history-item').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="area-filter"]').element.value).toBe('computer_science')
  expect(wrapper.get('[data-testid="applied-filters"]').text()).toBe('Computer science · 2020–2025')
  expect(wrapper.findAll('.paper')).toHaveLength(1)
})

it('links citations to the coverage table and lists report sections', async () => {
  window.localStorage.setItem('literature-active-review', 'job')
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({
      id: 'job', topic: 'graphs', status: 'completed',
      review: '# Overview\nA finding [P1, P2] and [P9].\n## Research gaps\nMore.',
      evidence: [{ id: 'P1', title: 'One', coverage: 'full PDF' }, { id: 'P2', title: 'Two', coverage: 'truncated PDF' }],
    })))
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.findAll('.markdown a.cite').map(a => a.attributes('href'))).toEqual(['#source-P1', '#source-P2'])
  expect(wrapper.get('.markdown').text()).toContain('[P9]')
  expect(wrapper.find('.toc').exists()).toBe(false)
  await wrapper.get('.toc-toggle').trigger('click')
  expect(wrapper.findAll('.toc a').map(a => a.text())).toEqual(['Overview', 'Research gaps', 'Sources & coverage'])
  expect(wrapper.get('.markdown h2').attributes('id')).toBe(wrapper.findAll('.toc a')[1].attributes('href').slice(1))
  expect(wrapper.get('#source-P2 .cov').classes()).toContain('warning')
  await wrapper.findAll('.toc a')[1].trigger('click')
  expect(wrapper.find('.toc').exists()).toBe(false)
})

it('shows review steps from backend progress messages', async () => {
  window.localStorage.setItem('literature-active-review', 'job')
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({
      id: 'job', topic: 'graphs', status: 'running', progress: 'Reading paper 2/2: Second',
      papers: [paper, { ...paper, url: `${paper.url}b`, title: 'Second' }],
    })))
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('.steps li.now').text()).toContain('2 / 2')
  expect(wrapper.findAll('.reading-list li').map(li => li.classes()[0])).toEqual(['done', 'reading'])
})

it('offers regeneration only for the selection that produced the shown review', async () => {
  const second = { ...paper, url: `${paper.url}b`, title: 'Second' }
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ items: [{
      id: 'old-review', kind: 'review', topic: 'graphs', status: 'completed', paper_count: 1,
      created_at: '2026-01-01T00:00:00Z',
    }], has_more: false }))
    .mockImplementationOnce(() => respond({
      id: 'old-review', kind: 'review', topic: 'graphs', status: 'completed', papers: [paper, second],
      review: '# Old', evidence: [],
    })))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('[data-testid="history-toggle"]').trigger('click')
  await flushPromises()
  await wrapper.get('.history-item').trigger('click')
  await flushPromises()
  const action = () => wrapper.get('.selection-bar button:last-child')
  expect(action().text()).toBe('Regenerate review')
  await wrapper.findAll('input[type="checkbox"]')[1].setValue(false)
  expect(action().text()).toBe('Generate review')
})

it('allows subscription CLI generation without an API key and submits study details', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond({
      ...config, has_api_key: false, ready: true, model: 'CLI default', ai_backend: 'claude_cli',
      ai_label: 'Claude Code · Claude subscription', setup_hint: 'Run claude auth login.',
    }))
    .mockImplementationOnce(() => respond({ papers: [paper] }))
    .mockImplementationOnce(() => respond({ id: 'intro', status: 'queued' }))
    .mockImplementationOnce(() => respond({ id: 'intro', status: 'running' }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('[data-testid="ai-connection-mode"]').element.value).toBe('claude_cli')
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  await wrapper.get('[data-testid="output-mode"]').setValue('introduction')
  await wrapper.get('[data-testid="study-units"]').setValue('chip layouts')
  await wrapper.get('[data-testid="study-research_question"]').setValue('Does the method transfer?')
  const generate = wrapper.findAll('button').find(button => button.text() === 'Generate introduction')
  expect(generate.element.disabled).toBe(false)
  await generate.trigger('click')
  await flushPromises()
  const submitted = JSON.parse(fetchMock.mock.calls[2][1].body)
  expect(submitted.options.mode).toBe('introduction')
  expect(submitted.options.units).toBe('chip layouts')
  expect(submitted.options.research_question).toBe('Does the method transfer?')
  expect(submitted).not.toHaveProperty('ai_backend')
  expect(submitted).not.toHaveProperty('api_key')
})

it('offers the last five calendar years without preventing historical literature searches', async () => {
  vi.stubGlobal('fetch', vi.fn(() => respond(config)))
  wrapper = mount(App)
  await flushPromises()
  const year = new Date().getFullYear()
  await wrapper.get('[data-testid="recent-years"]').trigger('click')
  expect(wrapper.get('[data-testid="year-from"]').element.value).toBe(String(year - 4))
  expect(wrapper.get('[data-testid="year-to"]').element.value).toBe(String(year))
  await wrapper.findAll('button').find(button => button.text() === 'Reset filters').trigger('click')
  expect(wrapper.get('[data-testid="year-from"]').element.value).toBe('')
  expect(wrapper.get('[data-testid="year-to"]').element.value).toBe('')
})

it('restores introduction settings and shows citation checks with supplied page links', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond(config))
    .mockImplementationOnce(() => respond({ items: [{
      id: 'intro', kind: 'review', topic: 'graphs', status: 'completed', paper_count: 1,
      output_mode: 'introduction', created_at: '2026-01-01T00:00:00Z',
    }], has_more: false }))
    .mockImplementationOnce(() => respond({
      id: 'intro', kind: 'review', topic: 'graphs', status: 'completed', papers: [paper],
      options: { mode: 'introduction', units: 'chip layouts' },
      review: '# Introduction\nEvidence [P1, p. 7]. [待補：研究目標]',
      evidence: [{ id: 'P1', title: paper.title, coverage: 'sampled PDF' }],
      checks: [{ name: 'Evidence completeness', status: 'warning', details: 'Limited text coverage: P1.' }],
    }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('[data-testid="history-toggle"]').trigger('click')
  await flushPromises()
  await wrapper.get('.history-item').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="output-mode"]').element.value).toBe('introduction')
  expect(wrapper.get('[data-testid="study-units"]').element.value).toBe('chip layouts')
  expect(wrapper.get('.report-head h2').text()).toBe('Introduction: graphs')
  expect(wrapper.get('.markdown a.cite').text()).toBe('P1, p. 7')
  expect(wrapper.get('.report-checks').text()).toContain('Limited text coverage')
  expect(wrapper.get('.selection-bar button:last-child').text()).toBe('Regenerate introduction')
  await wrapper.get('[data-testid="study-units"]').setValue('different units')
  expect(wrapper.get('.selection-bar button:last-child').text()).toBe('Generate introduction')
  expect(fetchMock.mock.calls.every(call => !call[1]?.method)).toBe(true)
})

it('enables Codex generation only after the frontend login completes', async () => {
  vi.useFakeTimers()
  let connected = false
  let started = false
  vi.stubGlobal('fetch', vi.fn(path => {
    if (path === '/api/config') return respond({ ...config, ready: true, has_api_key: false, ai_backend: 'codex_cli' })
    if (path === '/api/search') return respond({ papers: [paper] })
    if (path === '/api/auth/chatgpt/start') {
      started = true
      return respond({ status: 'pending', connected: false, user_code: 'ABCD-1234', verification_url: 'https://auth.openai.com/codex/device' })
    }
    if (path === '/api/auth/chatgpt') return respond({ status: connected ? 'connected' : started ? 'pending' : 'disconnected', connected, plan: connected ? 'plus' : null })
    throw new Error(`Unexpected request ${path}`)
  }))
  wrapper = mount(App)
  await flushPromises()
  await wrapper.get('input[placeholder^="e.g."]').setValue('graphs')
  await wrapper.get('form.search').trigger('submit')
  await flushPromises()
  expect(wrapper.get('.selection-bar button:last-child').element.disabled).toBe(true)
  await wrapper.get('[data-testid="chatgpt-connect"]').trigger('click')
  await flushPromises()
  connected = true
  await vi.advanceTimersByTimeAsync(2000)
  await flushPromises()
  expect(wrapper.get('.selection-bar button:last-child').element.disabled).toBe(false)
  expect(wrapper.get('.connection-status').text()).toContain('connected')
})

it('keeps appearance and AI in gear settings and verifies API before enabling models', async () => {
  const fetchMock = vi.fn()
    .mockImplementationOnce(() => respond({ ...config, has_api_key: false, api_verified: false, ready: false }))
    .mockImplementationOnce(() => respond({ ...config, ai_backend: 'openai_api', api_verified: true, ready: true }))
  vi.stubGlobal('fetch', fetchMock)
  wrapper = mount(App)
  await flushPromises()
  expect(wrapper.get('summary[aria-label="設定"]').text()).toContain('設定')
  expect(wrapper.get('.settings .theme-picker').exists()).toBe(true)
  expect(wrapper.findComponent({ name: 'ModelPicker' }).props('enabled')).toBe(false)
  await wrapper.get('[data-testid="api-key"]').setValue('private-api-key')
  await wrapper.get('.api-connection').trigger('submit')
  await flushPromises()
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ backend: 'openai_api', api_key: 'private-api-key' })
  expect(wrapper.get('[data-testid="api-key"]').element.value).toBe('')
  expect(wrapper.findComponent({ name: 'ModelPicker' }).props('enabled')).toBe(true)
  await wrapper.get('[data-testid="api-key"]').setValue('replacement-key')
  expect(wrapper.findComponent({ name: 'ModelPicker' }).props('enabled')).toBe(false)
})
