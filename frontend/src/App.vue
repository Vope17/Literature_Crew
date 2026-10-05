<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ReportView from './ReportView.vue'
import ReviewProgress from './ReviewProgress.vue'

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
const filtersOpen = ref(false)
const compact = ref(false)
const expandedAbstracts = ref([])
const historyKind = ref('all')
const visibleHistory = computed(() => historyKind.value === 'all'
  ? historyItems.value : historyItems.value.filter(item => item.kind === historyKind.value))
const configured = computed(() => !!model.value && hasServerKey.value)
const selectedPapers = computed(() => selected.value.map(i => papers.value[i]).filter(Boolean))
// The shown review was generated from exactly the current topic and selection.
const alreadyGenerated = computed(() => {
  const reviewed = result.value?.papers
  if (!reviewed?.length || result.value.topic !== searchedTopic.value) return false
  const urls = new Set(reviewed.map(paper => paper.url))
  return urls.size === selectedPapers.value.length && selectedPapers.value.every(paper => urls.has(paper.url))
})
const filterChips = computed(() => {
  const chips = []
  if (area.value !== 'all') {
    chips.push({ key: 'area', label: areas.value.find(item => item.value === area.value)?.label || area.value })
  }
  if (yearFrom.value !== '' || yearTo.value !== '') {
    chips.push({ key: 'years', label: `${yearFrom.value || 'Any year'} – ${yearTo.value || 'present'}` })
  }
  if (limit.value !== 5) chips.push({ key: 'limit', label: `${limit.value} results` })
  return chips
})

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

function shortCitation(paper) {
  const surname = (paper.authors?.[0] || 'Unknown').trim().split(/\s+/).at(-1)
  return `${surname} ${paper.year}`
}

function clearChip(key) {
  if (key === 'area') area.value = 'all'
  if (key === 'years') { yearFrom.value = ''; yearTo.value = '' }
  if (key === 'limit') limit.value = 5
}

function toggleAbstract(url) {
  expandedAbstracts.value = expandedAbstracts.value.includes(url)
    ? expandedAbstracts.value.filter(item => item !== url) : [...expandedAbstracts.value, url]
}

function selectTop(count) {
  selected.value = papers.value.slice(0, Math.min(count, maxPapers.value)).map((_, i) => i)
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
    expandedAbstracts.value = []
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
      papers: selectedPapers.value,
    })
    activeReview.value = {
      ...job, topic: searchedTopic.value, papers: selectedPapers.value, progress: 'Waiting to generate the review…',
    }
    rememberReview(job.id)
    // Each status request is short; the crew runs independently on the backend.
    void pollReview(job.id)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
  }
}

function resetFilters() {
  area.value = 'all'
  yearFrom.value = ''
  yearTo.value = ''
}
</script>

<template>
  <main :class="{ 'with-bar': searched && papers.length }">
    <header class="topbar">
      <div class="brand">Literature Crew<span>.</span></div>
      <details class="settings" :open="!configured">
        <summary class="chip" :class="{ off: !configured }">
          <span class="dot" aria-hidden="true"></span>
          <strong data-testid="configured-model">{{ model || 'Not configured' }}</strong>
          <span class="muted">{{ configured ? 'ready' : 'setup needed' }}</span>
        </summary>
        <div class="settings-body">
          <p v-if="!configured" class="notice warning">
            Set OPENAI_API_KEY and MODEL in backend/.env, then restart the backend. Paper search is available without them.
          </p>
          <p class="muted">Configuration is loaded from backend/.env. Restart the backend after editing it.</p>
          <p class="muted">Search is free. Generating a review sends paper text to the model provider and uses API credits.
            API keys stay on the backend.</p>
        </div>
      </details>
      <span class="spacer"></span>
      <button class="secondary" data-testid="history-toggle" :aria-expanded="historyExpanded"
        aria-controls="history-content" @click="toggleHistory">
        {{ historyExpanded ? 'Hide history' : 'History' }}
      </button>
    </header>

    <div class="workspace" :class="{ 'has-history': historyExpanded }">
      <div class="primary">
        <form class="panel search" @submit.prevent="search">
          <div class="search-row">
            <input v-model="topic" required maxlength="500" :disabled="!!busy" aria-label="Research topic"
              placeholder="e.g. Graph neural networks for semiconductor layout analysis" />
            <button type="submit" :disabled="!!busy || !!retrySeconds || !topic.trim() || !!filterError">
              {{ retrySeconds ? `Retry in ${retrySeconds}s` : 'Search papers' }}
            </button>
          </div>
          <div class="chips-row">
            <span v-for="chip in filterChips" :key="chip.key" class="fchip">{{ chip.label }}
              <button type="button" :aria-label="`Remove ${chip.label}`" :disabled="!!busy" @click="clearChip(chip.key)">✕</button>
            </span>
            <button type="button" class="link" :aria-expanded="filtersOpen" aria-controls="search-filters"
              @click="filtersOpen = !filtersOpen">{{ filtersOpen ? '− Hide filters' : '+ Filters' }}</button>
          </div>
          <fieldset v-show="filtersOpen" id="search-filters" class="search-filters" :disabled="!!busy">
            <legend class="visually-hidden">Search filters</legend>
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
            <label>Results
              <select v-model="limit">
                <option v-for="n in 10" :key="n" :value="n">{{ n }}</option>
              </select>
            </label>
            <button class="secondary" type="button" @click="resetFilters">Reset filters</button>
            <p class="muted filter-hint">Year uses arXiv submission dates or Semantic Scholar publication years.
              Subject classifications vary by source.</p>
          </fieldset>
          <p v-if="filterError" class="notice error" role="alert">{{ filterError }}</p>
        </form>

        <p v-if="error" class="notice error" role="alert">{{ error }}</p>
        <p v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{ busy }}</p>
        <ReviewProgress v-if="activeReview" :job="activeReview" :elapsed="reviewElapsed" :can-retry="!!reviewError"
          @retry="pollReview(activeReview.id)" />
        <p v-if="reviewError" class="notice error" role="alert">{{ reviewError }}</p>

        <ReportView v-if="result" :result="result" />

        <section v-if="searched" class="results" :aria-busy="!!busy">
          <div class="section-heading">
            <div>
              <h2>Papers for “{{ searchedTopic }}”</h2>
              <p class="muted">{{ papers.length }} results from {{ searchSource }} · Choose up to {{ maxPapers }} papers</p>
              <p class="muted" data-testid="applied-filters">{{ appliedFilters }}</p>
            </div>
            <div v-if="papers.length" class="list-tools">
              <button class="link" type="button" :disabled="!!busy" @click="selectTop(3)">Select top 3</button>
              <button class="link" type="button" :disabled="!!busy || !selected.length" @click="selected = []">Clear</button>
              <div class="seg" role="group" aria-label="Paper list density">
                <button type="button" :class="{ on: !compact }" :aria-pressed="!compact" @click="compact = false">Detailed</button>
                <button type="button" :class="{ on: compact }" :aria-pressed="compact" @click="compact = true">Compact</button>
              </div>
            </div>
          </div>
          <p v-if="searchNotice" class="notice warning" role="status">{{ searchNotice }}</p>
          <p v-if="!papers.length" class="panel">No papers found. Try a shorter topic or different keywords.</p>
          <article v-for="(paper, i) in papers" :key="paper.url" class="panel paper"
            :class="{ chosen: selected.includes(i), compact }">
            <input :id="`paper-${i}`" v-model="selected" type="checkbox" :value="i"
              :disabled="!!busy || (!selected.includes(i) && selected.length >= maxPapers)" />
            <div>
              <div class="meta"><span>{{ paper.year }}</span><span class="tag">{{ searchSource === 'Semantic Scholar' ? 'via Semantic Scholar' : 'arXiv' }}</span></div>
              <h3><label :for="`paper-${i}`">{{ paper.title }}</label></h3>
              <template v-if="!compact">
                <p class="authors">{{ paper.authors.join(', ') }}</p>
                <p class="abstract" :class="{ open: expandedAbstracts.includes(paper.url) }">{{ paper.abstract }}</p>
                <div class="paper-links">
                  <button class="link" type="button" @click="toggleAbstract(paper.url)">
                    {{ expandedAbstracts.includes(paper.url) ? 'Show less' : 'Show more' }}</button>
                  <a :href="paper.url" target="_blank" rel="noopener noreferrer">View on arXiv ↗</a>
                </div>
              </template>
            </div>
          </article>
          <p v-if="papers.length" class="muted">arXiv includes preprints. SCI indexing and peer review are not verified.</p>
        </section>
      </div>

      <aside v-if="historyExpanded" id="history-content" class="panel history">
        <div class="history-heading">
          <h2>History</h2>
          <button class="link" :disabled="historyLoading" @click="loadHistory()">Refresh</button>
        </div>
        <div class="seg" role="group" aria-label="History type">
          <button v-for="kind in [['all', 'All'], ['review', 'Reviews'], ['search', 'Searches']]" :key="kind[0]"
            type="button" :class="{ on: historyKind === kind[0] }" :aria-pressed="historyKind === kind[0]"
            @click="historyKind = kind[0]">{{ kind[1] }}</button>
        </div>
        <p v-if="historyError" class="notice error" role="alert">{{ historyError }}</p>
        <p v-if="historyLoading" class="muted" role="status">Loading history…</p>
        <p v-else-if="!visibleHistory.length && !historyError" class="muted">Your searches and reviews will appear here.</p>
        <button v-for="item in visibleHistory" :key="item.id" type="button" class="history-item"
          :class="{ dim: item.kind === 'search' && !item.paper_count }"
          :disabled="!!openingHistory || !!busy" @click="openHistory(item.id)">
          <span class="icon" aria-hidden="true">{{ item.kind === 'review' ? '📄' : '🔍' }}</span>
          <span class="history-text">
            <strong>{{ item.topic }}</strong>
            <span class="muted">{{ item.kind === 'review' ? 'Review' : 'Search' }} ·
              {{ item.status === 'completed' ? (item.paper_count ? `${item.paper_count} papers` : 'no results') : item.status }} ·
              {{ new Date(item.created_at).toLocaleString() }}</span>
            <span v-if="openingHistory === item.id" class="muted">Opening…</span>
          </span>
        </button>
        <button v-if="historyHasMore" class="secondary" :disabled="historyLoading" @click="loadHistory(true)">Load more</button>
      </aside>
    </div>
    <footer>Literature Crew · arXiv + Semantic Scholar + CrewAI</footer>
  </main>

  <div v-if="searched && papers.length" class="selection-bar">
    <div class="selection-inner">
      <div class="slots" aria-hidden="true">
        <span v-for="n in maxPapers" :key="n" :class="{ filled: n <= selected.length }"></span>
      </div>
      <strong class="badge">{{ selected.length }} / {{ maxPapers }} selected</strong>
      <span class="muted picked">{{ selectedPapers.map(shortCitation).join(' · ') }}</span>
      <span class="spacer"></span>
      <button class="secondary" type="button" :disabled="!!busy || !selected.length" @click="selected = []">Clear</button>
      <button :disabled="!!busy || !!activeReview || !configured || !selected.length" @click="generate">{{ alreadyGenerated ? 'Regenerate review' : 'Generate review' }}</button>
    </div>
  </div>
</template>
