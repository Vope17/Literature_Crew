<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const topic = ref('')
const searchedTopic = ref('')
const limit = ref(5)
const area = ref('all')
const areas = ref([{ value: 'all', label: 'All subjects' }])
const yearFrom = ref('')
const yearTo = ref('')
const maxYear = new Date().getFullYear() + 1
const appliedFilters = ref('')
const filterError = computed(() => {
  for (const year of [yearFrom.value, yearTo.value]) {
    if (year !== '' && (!Number.isInteger(Number(year)) || Number(year) < 1900 || Number(year) > maxYear)) {
      return `Years must be whole numbers between 1900 and ${maxYear}.`
    }
  }
  return yearFrom.value !== '' && yearTo.value !== '' && Number(yearFrom.value) > Number(yearTo.value)
    ? 'Start year must not be later than end year.' : ''
})
const papers = ref([])
const selected = ref([])
const model = ref('')
const hasServerKey = ref(false)
const maxPapers = ref(5)
const busy = ref('')
const error = ref('')
const searched = ref(false)
const searchNotice = ref('')
const searchSource = ref('')
const result = ref(null)
const activeReview = ref(null)
const reviewError = ref('')
const historyExpanded = ref(false)
const historyItems = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const historyHasMore = ref(false)
const openingHistory = ref('')
const retryUntil = ref(0)
const now = ref(Date.now())
const retrySeconds = computed(() => Math.max(0, Math.ceil((retryUntil.value - now.value) / 1000)))
let retryTimer
let pollTimer
let mounted = true
const reviewElapsed = computed(() => activeReview.value?.created_at
  ? Math.max(0, Math.floor((now.value - Date.parse(activeReview.value.created_at)) / 1000)) : 0)
const markdown = new MarkdownIt({ html: false, linkify: true })
const renderedReview = computed(() => DOMPurify.sanitize(markdown.render(result.value?.review || '')))

async function request(path, body) {
  let response
  const signal = AbortSignal.timeout(path === 'search' ? 180_000 : 15_000)
  try {
    response = await fetch(`/api/${path}`, body ? {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    } : { signal })
  } catch {
    throw new Error('Cannot reach the server. Check that the Python backend is running.')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const failure = new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Please retry.')
    failure.status = response.status
    failure.retryAfter = Number(response.headers?.get('Retry-After')) || 0
    throw failure
  }
  return data
}

onMounted(async () => {
  retryTimer = setInterval(() => { now.value = Date.now() }, 1000)
  try {
    const config = await request('config')
    model.value = config.model
    hasServerKey.value = config.has_api_key
    maxPapers.value = config.max_papers
    areas.value = config.search_areas || areas.value
  } catch (err) {
    error.value = err.message
  }
  try {
    const savedId = window.localStorage.getItem('literature-active-review')
    if (savedId) {
      activeReview.value = { id: savedId, status: 'queued', progress: 'Checking your review…' }
      await pollReview(savedId)
    }
  } catch { /* Storage can be unavailable in private browsing. */ }
})

onBeforeUnmount(() => {
  mounted = false
  clearInterval(retryTimer)
  clearTimeout(pollTimer)
})

function filterSummary(filters = {}) {
  const subject = areas.value.find(item => item.value === filters.area)?.label || 'All subjects'
  const years = filters.year_from || filters.year_to
    ? `${filters.year_from || 'Any year'}–${filters.year_to || 'present'}` : 'Any year'
  return `${subject} · ${years}`
}

function rememberReview(id) {
  try {
    if (id) window.localStorage.setItem('literature-active-review', id)
    else window.localStorage.removeItem('literature-active-review')
  } catch { /* Polling works even when local storage is unavailable. */ }
}

async function pollReview(id) {
  clearTimeout(pollTimer)
  reviewError.value = ''
  try {
    const job = await request(`reviews/${id}`)
    if (!mounted || activeReview.value?.id !== id) return
    if (job.status === 'completed' || job.status === 'failed') {
      activeReview.value = null
      rememberReview(null)
      if (job.status === 'completed') result.value = job
      else reviewError.value = job.error || 'Review failed. Please try again.'
      if (historyExpanded.value) await loadHistory()
    } else {
      activeReview.value = job
      pollTimer = setTimeout(() => pollReview(id), 2000)
    }
  } catch (err) {
    if (mounted && activeReview.value?.id === id) {
      reviewError.value = err.message
      if (err.status === 404) {
        activeReview.value = null
        rememberReview(null)
      }
    }
  }
}

async function loadHistory(append = false) {
  if (historyLoading.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const data = await request(`history?limit=20&offset=${append ? historyItems.value.length : 0}`)
    historyItems.value = append ? [...historyItems.value, ...data.items] : data.items
    historyHasMore.value = data.has_more
  } catch (err) {
    historyError.value = err.message
  } finally {
    historyLoading.value = false
  }
}

function toggleHistory() {
  historyExpanded.value = !historyExpanded.value
  if (historyExpanded.value) loadHistory()
}

async function openHistory(id) {
  openingHistory.value = id
  historyError.value = ''
  try {
    const saved = await request(`history/${id}`)
    if (!activeReview.value) reviewError.value = ''
    topic.value = saved.topic
    searchedTopic.value = saved.topic
    papers.value = saved.papers
    selected.value = saved.papers.slice(0, maxPapers.value).map((_, i) => i)
    searched.value = true
    searchSource.value = saved.source || 'saved review'
    searchNotice.value = saved.notice || ''
    appliedFilters.value = saved.kind === 'search' ? filterSummary(saved.filters) : ''
    if (saved.kind === 'search') {
      area.value = saved.filters?.area || 'all'
      yearFrom.value = saved.filters?.year_from ?? ''
      yearTo.value = saved.filters?.year_to ?? ''
      result.value = null
    } else if (saved.status === 'completed') {
      result.value = saved
    } else if (saved.status === 'failed') {
      result.value = null
      reviewError.value = saved.error
    } else {
      activeReview.value = saved
      rememberReview(id)
      await pollReview(id)
    }
  } catch (err) {
    historyError.value = err.message
  } finally {
    openingHistory.value = ''
  }
}

async function search() {
  if (busy.value || retrySeconds.value || !topic.value.trim() || filterError.value) return
  busy.value = 'Searching papers…'
  error.value = ''
  try {
    const filters = {
      area: area.value,
      year_from: yearFrom.value === '' ? null : Number(yearFrom.value),
      year_to: yearTo.value === '' ? null : Number(yearTo.value),
    }
    const data = await request('search', { topic: topic.value.trim(), limit: limit.value, ...filters })
    papers.value = data.papers
    searchNotice.value = data.notice || ''
    searchSource.value = data.source || 'arXiv'
    searchedTopic.value = topic.value.trim()
    appliedFilters.value = filterSummary(filters)
    selected.value = data.papers.slice(0, 3).map((_, i) => i)
    searched.value = true
    result.value = null
    if (historyExpanded.value) await loadHistory()
  } catch (err) {
    error.value = err.message
    if (err.retryAfter) {
      now.value = Date.now()
      retryUntil.value = now.value + err.retryAfter * 1000
    }
  } finally {
    busy.value = ''
  }
}

async function generate() {
  if (busy.value || activeReview.value || !selected.value.length) return
  if (!model.value || !hasServerKey.value) {
    error.value = 'Set OPENAI_API_KEY and MODEL in backend/.env, then restart the backend.'
    return
  }
  busy.value = 'Queuing your review…'
  error.value = ''
  reviewError.value = ''
  result.value = null
  try {
    const job = await request('review', {
      topic: searchedTopic.value,
      papers: selected.value.map(i => papers.value[i]),
    })
    activeReview.value = { ...job, topic: searchedTopic.value, progress: 'Waiting to generate the review…' }
    rememberReview(job.id)
    // Each status request is short; the crew runs independently on the backend.
    void pollReview(job.id)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
  }
}

function download(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function resetFilters() {
  area.value = 'all'
  yearFrom.value = ''
  yearTo.value = ''
}
</script>

<template>
  <main>
    <header>
      <span class="eyebrow">YOUR RESEARCH WORKSPACE</span>
      <h1>Literature Crew<span>.</span></h1>
      <p>Find papers. Compare evidence. Start your literature review.</p>
    </header>

    <details class="panel settings" open>
      <summary>Analysis configuration</summary>
      <p>Model: <strong data-testid="configured-model">{{ model || 'Not configured' }}</strong></p>
      <p v-if="!hasServerKey || !model" class="notice warning">
        Set OPENAI_API_KEY and MODEL in backend/.env, then restart the backend. Paper search is available without them.
      </p>
      <p class="muted">Configuration is loaded from backend/.env. Restart the backend after editing it.</p>
      <p class="muted">Search is free. Generating a review sends paper text to the model provider and uses API credits.
        API keys stay on the backend.</p>
    </details>

    <section class="panel history">
      <button class="secondary" data-testid="history-toggle" :aria-expanded="historyExpanded"
        aria-controls="history-content" @click="toggleHistory">
        {{ historyExpanded ? 'Hide history' : 'Show history' }}
      </button>
      <div v-if="historyExpanded" id="history-content">
        <div class="section-heading history-heading">
          <h2>Saved history</h2>
          <button class="secondary" :disabled="historyLoading" @click="loadHistory()">Refresh history</button>
        </div>
        <p v-if="historyError" class="notice error" role="alert">{{ historyError }}</p>
        <p v-if="historyLoading" class="muted" role="status">Loading history…</p>
        <p v-else-if="!historyItems.length && !historyError" class="muted">Your searches and reviews will appear here.</p>
        <article v-for="item in historyItems" :key="item.id" class="history-item">
          <div>
            <h3>{{ item.topic }}</h3>
            <p class="muted">{{ item.kind === 'review' ? 'Review' : 'Search' }} · {{ item.status }} ·
              {{ item.paper_count }} papers · {{ new Date(item.created_at).toLocaleString() }}</p>
            <p v-if="item.model" class="muted">{{ item.model }}</p>
          </div>
          <button class="secondary" :disabled="!!openingHistory || !!busy" @click="openHistory(item.id)">
            {{ openingHistory === item.id ? 'Opening…' : 'Open result' }}
          </button>
        </article>
        <button v-if="historyHasMore" class="secondary" :disabled="historyLoading" @click="loadHistory(true)">Load more</button>
      </div>
    </section>

    <form class="panel search" @submit.prevent="search">
      <div class="search-row">
      <label class="topic">Research topic
        <input v-model="topic" required maxlength="500" :disabled="!!busy"
          placeholder="e.g. Graph neural networks for semiconductor layout analysis" />
      </label>
      <label>Results
        <select v-model="limit" :disabled="!!busy">
          <option v-for="n in 10" :key="n" :value="n">{{ n }}</option>
        </select>
      </label>
      <button type="submit" :disabled="!!busy || !!retrySeconds || !topic.trim() || !!filterError">
        {{ retrySeconds ? `Retry in ${retrySeconds}s` : 'Search papers' }}
      </button>
      </div>
      <fieldset class="search-filters" :disabled="!!busy">
        <legend>Search filters</legend>
        <label>Subject area
          <select v-model="area" data-testid="area-filter">
            <option v-for="item in areas" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label>From year
          <input v-model="yearFrom" data-testid="year-from" type="number" min="1900" :max="maxYear" step="1" placeholder="Any" />
        </label>
        <label>To year
          <input v-model="yearTo" data-testid="year-to" type="number" min="1900" :max="maxYear" step="1" placeholder="Any" />
        </label>
        <button class="secondary" type="button" @click="resetFilters">Reset filters</button>
      </fieldset>
      <p v-if="filterError" class="notice error" role="alert">{{ filterError }}</p>
      <p class="muted filter-hint">Year uses arXiv submission dates or Semantic Scholar publication years. Subject classifications vary by source.</p>
    </form>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{ busy }}</p>
    <section v-if="activeReview" class="panel review-progress" aria-live="polite">
      <h2>Generating review for “{{ activeReview.topic || 'your topic' }}”</h2>
      <p class="notice progress" role="status"><span class="spinner"></span>
        {{ activeReview.progress }} <span v-if="reviewElapsed">· {{ reviewElapsed }}s elapsed</span>
      </p>
      <p class="muted">You can keep searching while the review runs. Refreshing this page reconnects to it.</p>
      <button v-if="reviewError" class="secondary" @click="pollReview(activeReview.id)">Retry status check</button>
    </section>
    <p v-if="reviewError" class="notice error" role="alert">{{ reviewError }}</p>

    <section v-if="searched" class="results" :aria-busy="!!busy">
      <div class="section-heading">
        <div>
          <h2>Papers for “{{ searchedTopic }}”</h2>
          <p class="muted">{{ papers.length }} results from {{ searchSource }} · Choose up to {{ maxPapers }} papers</p>
          <p class="muted" data-testid="applied-filters">{{ appliedFilters }}</p>
        </div>
        <span v-if="papers.length" class="badge">{{ selected.length }} selected</span>
      </div>
      <p v-if="searchNotice" class="notice warning" role="status">{{ searchNotice }}</p>
      <p v-if="!papers.length" class="panel">No papers found. Try a shorter topic or different keywords.</p>
      <article v-for="(paper, i) in papers" :key="paper.url" class="panel paper" :class="{ chosen: selected.includes(i) }">
        <input :id="`paper-${i}`" v-model="selected" type="checkbox" :value="i"
          :disabled="!!busy || (!selected.includes(i) && selected.length >= maxPapers)" />
        <div>
          <span class="muted">{{ paper.year }}</span>
          <h3><label :for="`paper-${i}`">{{ paper.title }}</label></h3>
          <p class="authors">{{ paper.authors.join(', ') }}</p>
          <details><summary>Read abstract</summary><p>{{ paper.abstract }}</p></details>
          <a :href="paper.url" target="_blank" rel="noopener noreferrer">View on arXiv ↗</a>
        </div>
      </article>
      <div v-if="papers.length" class="actions">
        <p class="muted">arXiv includes preprints. SCI indexing and peer review are not verified.</p>
        <button :disabled="!!busy || !!activeReview || !hasServerKey || !selected.length || !model" @click="generate">Generate review</button>
      </div>
    </section>

    <section v-if="result" class="panel report">
      <div class="section-heading">
        <h2>{{ result.topic ? `Review: ${result.topic}` : 'Your literature review' }}</h2>
        <div class="downloads">
          <button class="secondary" @click="download(result.review, 'review.md', 'text/markdown')">Markdown ↓</button>
          <button class="secondary" @click="download(JSON.stringify(result.evidence, null, 2), 'evidence.json', 'application/json')">Evidence JSON ↓</button>
        </div>
      </div>
      <p class="muted">Saved review<span v-if="result.model"> · {{ result.model }}</span>. Check claims against the original papers.</p>
      <template v-for="item in result.evidence" :key="item.id">
        <p v-if="item.coverage !== 'full PDF'" class="notice warning">{{ item.id }}: {{ item.title }} — {{ item.coverage }}.</p>
      </template>
      <div v-if="result.evidence.some(item => item.stored_pdf_url)" class="saved-pdfs">
        <h3>Saved PDFs</h3>
        <p v-for="item in result.evidence.filter(item => item.stored_pdf_url)" :key="item.id">
          <a :href="item.stored_pdf_url" download>{{ item.id }}: {{ item.title }} ↓</a>
        </p>
      </div>
      <div class="markdown" v-html="renderedReview"></div>
    </section>
    <footer>Literature Crew · arXiv + Semantic Scholar + CrewAI</footer>
  </main>
</template>
