<script setup>
import { t, locale } from './i18n'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ReportView from './ReportView.vue'
import ReviewProgress from './ReviewProgress.vue'
import ReviewOptions from './ReviewOptions.vue'
import ChatGPTLogin from './ChatGPTLogin.vue'
import ModelPicker from './ModelPicker.vue'
import ThemePicker from './ThemePicker.vue'
import LanguagePicker from './LanguagePicker.vue'
import { defaultReviewOptions } from './reviewOptions'

const topic = ref('')
const searchedTopic = ref('')
const limit = ref(5)
const area = ref('all')
const areas = ref([{ value: 'all', label: 'All subjects' }])
const yearFrom = ref('')
const yearTo = ref('')
const maxYear = new Date().getFullYear() + 1
const appliedFilters = ref('')
const filterOverrides = ref([])
function pinFilter(key) {
  if (!filterOverrides.value.includes(key)) filterOverrides.value.push(key)
}
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
const selectedModel = ref('')
const hasServerKey = ref(false)
const connectionMode = ref('openai_api')
const connectionId = ref('')
const connectionBusy = ref(false)
const connectionError = ref('')
const apiKey = ref('')
const apiVerified = ref(false)
const claudeConnected = ref(false)
const settingsOpen = ref(false)
const aiBackend = ref('openai_api')
const aiLabel = ref('OpenAI API')
const aiReady = ref(false)
const chatgptConnected = ref(false)
const setupHint = ref('Set OPENAI_API_KEY and MODEL in backend/.env, then restart the backend.')
const reviewOptions = ref(defaultReviewOptions())
const maxPapers = ref(5)
const busy = ref('')
const error = ref('')
const searched = ref(false)
const searchNotice = ref('')
const searchKeywords = ref([])
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
const configured = computed(() => {
  if (connectionMode.value !== aiBackend.value || connectionBusy.value) return false
  if (aiBackend.value === 'openai_api') return apiVerified.value && hasServerKey.value && (aiReady.value || !!selectedModel.value)
  if (aiBackend.value === 'codex_cli') return aiReady.value && chatgptConnected.value
  return aiReady.value && claudeConnected.value
})
const canLoadModels = computed(() => configured.value)
const selectedPapers = computed(() => selected.value.map(i => papers.value[i]).filter(Boolean))
const generateLabel = computed(() => {
  const name = reviewOptions.value.mode === 'introduction' ? 'introduction' : 'review'
  return `${alreadyGenerated.value ? 'Regenerate' : 'Generate'} ${name}`
})
// The shown review was generated from exactly the current topic and selection.
const alreadyGenerated = computed(() => {
  const reviewed = result.value?.papers
  if (!reviewed?.length || result.value.topic !== searchedTopic.value) return false
  if (result.value.ai_backend && result.value.ai_backend !== aiBackend.value) return false
  if (selectedModel.value && result.value.model !== selectedModel.value) return false
  if (JSON.stringify({ ...defaultReviewOptions(), ...result.value.options }) !== JSON.stringify(reviewOptions.value)) return false
  const urls = new Set(reviewed.map(paper => paper.url))
  return urls.size === selectedPapers.value.length && selectedPapers.value.every(paper => urls.has(paper.url))
})
const filterChips = computed(() => {
  const chips = []
  if (area.value !== 'all') {
    chips.push({ key: 'area', label: t(areas.value.find(item => item.value === area.value)?.label || area.value) })
  }
  if (yearFrom.value !== '' || yearTo.value !== '') {
    chips.push({ key: 'years', label: `${yearFrom.value || t('Any year')} – ${yearTo.value || t('present')}` })
  }
  if (limit.value !== 5) chips.push({ key: 'limit', label: t('{count} results', { count: limit.value }) })
  return chips
})

async function request(path, body) {
  let response
  const signal = AbortSignal.timeout(path === 'search' ? 310_000 : path === 'ai/connection' ? 60_000 : 15_000)
  try {
    response = await fetch(`/api/${path}`, body ? {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    } : { signal, cache: 'no-store' })
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

function applyConnection(config) {
  connectionId.value = config.connection_id || ''
  model.value = config.model
  hasServerKey.value = config.has_api_key
  aiBackend.value = config.ai_backend || 'openai_api'
  connectionMode.value = aiBackend.value
  aiLabel.value = config.ai_label || 'OpenAI API'
  aiReady.value = config.ready ?? (!!config.model && !!config.has_api_key)
  apiVerified.value = config.api_verified === true
  claudeConnected.value = config.connection_verified ?? config.ready ?? false
  chatgptConnected.value = false
  selectedModel.value = ''
  setupHint.value = config.setup_hint || setupHint.value
}

async function switchConnection() {
  connectionError.value = ''
  apiVerified.value = false
  selectedModel.value = ''
  if (connectionMode.value === 'openai_api') return
  apiKey.value = ''
  await connectAI()
}

async function connectAI() {
  if (connectionBusy.value) return
  connectionBusy.value = true
  connectionError.value = ''
  try {
    const config = await request('ai/connection', {
      backend: connectionMode.value,
      ...(connectionMode.value === 'openai_api' && apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}),
    })
    applyConnection(config)
    apiKey.value = ''
  } catch (err) {
    connectionError.value = err.message
  } finally {
    connectionBusy.value = false
  }
}

function editingApiKey() {
  apiVerified.value = false
  selectedModel.value = ''
}

function modelConnectionError(message) {
  apiVerified.value = false
  claudeConnected.value = false
  chatgptConnected.value = false
  connectionError.value = message
}

onMounted(async () => {
  retryTimer = setInterval(() => { now.value = Date.now() }, 1000)
  try {
    const config = await request('config')
    applyConnection(config)
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
  const subject = t(areas.value.find(item => item.value === filters.area)?.label || 'All subjects')
  const years = filters.year_from || filters.year_to
    ? `${filters.year_from || t('Any year')}–${filters.year_to || t('present')}` : t('Any year')
  return `${subject} · ${years}`
}

function shortCitation(paper) {
  const surname = (paper.authors?.[0] || 'Unknown').trim().split(/\s+/).at(-1)
  return `${surname} ${paper.year}`
}

function clearChip(key) {
  pinFilter(key)
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
    searchKeywords.value = saved.keywords || []
    appliedFilters.value = saved.kind === 'search' ? saved.filters : null
    if (saved.kind === 'search') {
      area.value = saved.filters?.area || 'all'
      yearFrom.value = saved.filters?.year_from ?? ''
      yearTo.value = saved.filters?.year_to ?? ''
      limit.value = saved.filters?.limit ?? 5
      filterOverrides.value = []
      result.value = null
    } else if (saved.status === 'completed') {
      result.value = saved
      reviewOptions.value = { ...defaultReviewOptions(), ...saved.options }
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
  if (!configured.value) {
    error.value = 'Connect AI in settings to extract search keywords.'
    settingsOpen.value = true
    return
  }
  busy.value = 'Extracting keywords with AI and searching papers…'
  error.value = ''
  try {
    const filters = {
      area: area.value,
      year_from: yearFrom.value === '' ? null : Number(yearFrom.value),
      year_to: yearTo.value === '' ? null : Number(yearTo.value),
    }
    const data = await request('search', {
      topic: topic.value.trim(), limit: limit.value, ...filters, filter_overrides: filterOverrides.value,
      ...(connectionId.value ? { connection_id: connectionId.value } : {}),
      ...(selectedModel.value ? { model: selectedModel.value } : {}),
    })
    papers.value = data.papers
    searchNotice.value = data.notice || ''
    searchKeywords.value = data.keywords || []
    searchSource.value = data.source || 'arXiv'
    searchedTopic.value = topic.value.trim()
    const effective = data.filters || { ...filters, limit: limit.value }
    appliedFilters.value = effective
    area.value = effective.area
    yearFrom.value = effective.year_from ?? ''
    yearTo.value = effective.year_to ?? ''
    limit.value = effective.limit ?? limit.value
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
  if (!configured.value) {
    error.value = setupHint.value
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
      options: reviewOptions.value,
      ...(connectionId.value ? { connection_id: connectionId.value } : {}),
      ...(selectedModel.value ? { model: selectedModel.value } : {}),
    })
    activeReview.value = {
      ...job, topic: searchedTopic.value, papers: selectedPapers.value, progress: 'Waiting to generate the review…',
    }
    rememberReview(job.id)
    // Each status request is short; the crew runs independently on the backend.
    void pollReview(job.id)
  } catch (err) {
    if ([401, 403, 409].includes(err.status)) {
      modelConnectionError(err.message)
      settingsOpen.value = true
    } else {
      error.value = err.message
    }
  } finally {
    busy.value = ''
  }
}

function resetFilters() {
  area.value = 'all'
  yearFrom.value = ''
  yearTo.value = ''
  limit.value = 5
  filterOverrides.value = []
}

function recentYears() {
  pinFilter('years')
  const currentYear = new Date().getFullYear()
  yearFrom.value = String(currentYear - 4)
  yearTo.value = String(currentYear)
}
</script>

<template>
  <main :class="{ 'with-bar': searched && papers.length }">
    <header class="topbar">
      <div class="brand">Literature Crew<span>.</span></div>
      <span class="spacer"></span>
      <details class="settings" :open="settingsOpen" @toggle="settingsOpen = $event.target.open">
        <summary class="chip settings-trigger" :aria-label="t('Settings')">
          <span aria-hidden="true">⚙</span> {{ t('Settings') }}
        </summary>
        <div class="settings-body">
          <h2>{{ t('Settings') }}</h2>
          <LanguagePicker />
          <ThemePicker />
          <label class="connection-label">{{ t('AI connection') }}
            <select v-model="connectionMode" data-testid="ai-connection-mode" :disabled="connectionBusy || !!activeReview"
              @change="switchConnection">
              <option value="codex_cli">{{ t('ChatGPT subscription') }}</option>
              <option value="openai_api">OpenAI API</option>
              <option value="claude_cli">{{ t('Claude Code subscription') }}</option>
            </select>
          </label>
          <template v-if="connectionMode === 'openai_api'">
            <form class="api-connection" @submit.prevent="connectAI">
              <label>{{ t('OpenAI API key') }}
                <input v-model="apiKey" type="password" data-testid="api-key" maxlength="1024" autocomplete="off"
                  spellcheck="false" :placeholder="t('Enter API key')" :disabled="connectionBusy || !!activeReview" @input="editingApiKey" />
              </label>
              <button type="submit" :disabled="connectionBusy || !!activeReview">{{ t(connectionBusy ? 'Verifying…' : 'Verify API connection') }}</button>
            </form>
            <p v-if="apiVerified" class="connection-success" role="status">{{ t('API connection verified') }}</p>
            <p v-else-if="hasServerKey" class="muted">{{ t('A server key is configured. Leave this blank to verify it, or enter a new key.') }}</p>
            <p class="muted">{{ t('Keys stay in server memory for up to 8 hours. Re-enter after restarting the service.') }}</p>
          </template>
          <ChatGPTLogin v-if="connectionMode === 'codex_cli' && aiBackend === 'codex_cli'" :key="connectionId" @connected="chatgptConnected = $event" />
          <button v-if="connectionMode === 'claude_cli' || (connectionMode === 'codex_cli' && connectionError)" class="secondary" type="button"
            :disabled="connectionBusy || !!activeReview" @click="connectAI">{{ t('Check subscription connection') }}</button>
          <p v-if="connectionBusy" class="muted" role="status">{{ t('Checking connection…') }}</p>
          <p v-if="connectionError" class="notice error" role="alert">{{ t(connectionError) }}</p>
          <ModelPicker v-model="selectedModel" :enabled="canLoadModels" :backend="aiBackend"
            :connection-id="connectionId" @connection-error="modelConnectionError"
            :default-model="model" :disabled="!!busy || !!activeReview || connectionBusy" />
          <p v-if="configured" class="connection-status">
          <strong data-testid="configured-model">{{ selectedModel || model || t('Not configured') }}</strong>
          <span class="muted">{{ t(configured ? (aiBackend === 'openai_api' ? 'ready' : aiBackend === 'codex_cli' ? 'connected' : 'CLI available') : 'setup needed') }}</span>
          </p>
          <p v-if="connectionMode === 'claude_cli' && !configured" class="muted">{{ t('Sign in to Claude Code on the server or container, then check the connection.') }}</p>
        </div>
      </details>
      <button class="secondary" data-testid="history-toggle" :aria-expanded="historyExpanded"
        aria-controls="history-content" @click="toggleHistory">
        {{ t(historyExpanded ? 'Hide history' : 'History') }}
      </button>
    </header>

    <div class="workspace" :class="{ 'has-history': historyExpanded }">
      <div class="primary">
        <form class="panel search" @submit.prevent="search">
          <div class="search-row">
            <textarea v-model="topic" required maxlength="10000" rows="3" :disabled="!!busy" :aria-label="t('Research topic')"
              :placeholder="t('e.g. Describe your research topic or question in Chinese or English')" />
            <button type="submit" :disabled="!!busy || !!retrySeconds || !topic.trim() || !!filterError">
              {{ t(retrySeconds ? `Retry in ${retrySeconds}s` : 'Search papers') }}
            </button>
          </div>
          <p class="muted">{{ t('AI extracts English search keywords from your description using your selected connection and model.') }} {{ topic.length }}/10,000 {{ t('characters.') }}</p>
          <div class="chips-row">
            <span v-for="chip in filterChips" :key="chip.key" class="fchip">{{ chip.label }}
              <button type="button" :aria-label="t('Remove {label}', { label: chip.label })" :disabled="!!busy" @click="clearChip(chip.key)">✕</button>
            </span>
            <button type="button" class="link" :aria-expanded="filtersOpen" aria-controls="search-filters"
              @click="filtersOpen = !filtersOpen">{{ t(filtersOpen ? '− Hide filters' : '+ Filters') }}</button>
          </div>
          <fieldset v-show="filtersOpen" id="search-filters" class="search-filters" :disabled="!!busy">
            <legend class="visually-hidden">{{ t('Search filters') }}</legend>
            <label>{{ t('Subject area') }}
              <select v-model="area" data-testid="area-filter" @change="pinFilter('area')">
                <option v-for="item in areas" :key="item.value" :value="item.value">{{ t(item.label) }}</option>
              </select>
            </label>
            <label>{{ t('From year') }}
              <input v-model="yearFrom" data-testid="year-from" type="number" min="1900" :max="maxYear" step="1" :placeholder="t('Any')" @input="pinFilter('years')" />
            </label>
            <label>{{ t('To year') }}
              <input v-model="yearTo" data-testid="year-to" type="number" min="1900" :max="maxYear" step="1" :placeholder="t('Any')" @input="pinFilter('years')" />
            </label>
            <label>{{ t('Results') }}
              <select v-model="limit" data-testid="limit-filter" @change="pinFilter('limit')">
                <option v-for="n in 10" :key="n" :value="n">{{ n }}</option>
              </select>
            </label>
            <button class="secondary" type="button" data-testid="recent-years" @click="recentYears">{{ t('Last 5 calendar years') }}</button>
            <button class="secondary" type="button" @click="resetFilters">{{ t('Reset filters') }}</button>
            <p class="muted">{{ t('AI fills subject, years and result count from your description. Manually changed fields take priority until Reset filters.') }}</p>
            <p v-if="filterOverrides.length" class="muted">{{ t('Manual overrides:') }} {{ filterOverrides.map(key => t(key === 'area' ? 'Subject area' : key === 'years' ? 'Years' : 'Results')).join(' · ') }}</p>
            <p class="muted filter-hint">{{ t('Year uses arXiv submission dates or Semantic Scholar publication years. Subject classifications vary by source.') }}</p>
          </fieldset>
          <p v-if="filterError" class="notice error" role="alert">{{ t(filterError) }}</p>
        </form>

        <p v-if="error" class="notice error" role="alert">{{ t(error) }}</p>
        <p v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{ t(busy) }}</p>
        <ReviewProgress v-if="activeReview" :job="activeReview" :elapsed="reviewElapsed" :can-retry="!!reviewError"
          @retry="pollReview(activeReview.id)" />
        <p v-if="reviewError" class="notice error" role="alert">{{ t(reviewError) }}</p>

        <ReportView v-if="result" :result="result" />

        <ReviewOptions v-if="searched && papers.length" v-model="reviewOptions" :disabled="!!busy || !!activeReview" />

        <section v-if="searched" class="results" :aria-busy="!!busy">
          <div class="section-heading">
            <div>
              <h2>{{ t('Papers for “{topic}”', { topic: searchedTopic }) }}</h2>
              <p class="muted">{{ t('{count} results from {source} · Choose up to {max} papers', { count: papers.length, source: searchSource, max: maxPapers }) }}</p>
              <p class="muted" data-testid="applied-filters">{{ appliedFilters ? filterSummary(appliedFilters) : '' }}</p>
              <p v-if="searchKeywords.length" class="muted" data-testid="search-keywords">{{ t('AI search keywords:') }} {{ searchKeywords.join(' · ') }}</p>
            </div>
            <div v-if="papers.length" class="list-tools">
              <button class="link" type="button" :disabled="!!busy" @click="selectTop(3)">{{ t('Select top 3') }}</button>
              <button class="link" type="button" :disabled="!!busy || !selected.length" @click="selected = []">{{ t('Clear') }}</button>
              <div class="seg" role="group" :aria-label="t('Paper list density')">
                <button type="button" :class="{ on: !compact }" :aria-pressed="!compact" @click="compact = false">{{ t('Detailed') }}</button>
                <button type="button" :class="{ on: compact }" :aria-pressed="compact" @click="compact = true">{{ t('Compact') }}</button>
              </div>
            </div>
          </div>
          <p v-if="searchNotice" class="notice warning" role="status">{{ t(searchNotice) }}</p>
          <p v-if="!papers.length" class="panel">{{ t('No papers found. Try a shorter topic or different keywords.') }}</p>
          <article v-for="(paper, i) in papers" :key="paper.url" class="panel paper"
            :class="{ chosen: selected.includes(i), compact }">
            <input :id="`paper-${i}`" v-model="selected" type="checkbox" :value="i"
              :disabled="!!busy || (!selected.includes(i) && selected.length >= maxPapers)" />
            <div>
              <div class="meta"><span>{{ paper.year }}</span><span class="tag">{{ t(searchSource === 'Semantic Scholar' ? 'via Semantic Scholar' : 'arXiv') }}</span></div>
              <h3><label :for="`paper-${i}`">{{ paper.title }}</label></h3>
              <template v-if="!compact">
                <p class="authors">{{ paper.authors.join(', ') }}</p>
                <p class="abstract" :class="{ open: expandedAbstracts.includes(paper.url) }">{{ paper.abstract }}</p>
                <div class="paper-links">
                  <button class="link" type="button" @click="toggleAbstract(paper.url)">
                    {{ t(expandedAbstracts.includes(paper.url) ? 'Show less' : 'Show more') }}</button>
                  <a :href="paper.url" target="_blank" rel="noopener noreferrer">{{ t('View on arXiv ↗') }}</a>
                </div>
              </template>
            </div>
          </article>
          <p v-if="papers.length" class="muted">{{ t('arXiv includes preprints. SCI indexing and peer review are not verified.') }}</p>
        </section>
      </div>

      <aside v-if="historyExpanded" id="history-content" class="panel history">
        <div class="history-heading">
          <h2>{{ t('History') }}</h2>
          <button class="link" :disabled="historyLoading" @click="loadHistory()">{{ t('Refresh') }}</button>
        </div>
        <div class="seg" role="group" :aria-label="t('History type')">
          <button v-for="kind in [['all', 'All'], ['review', 'Reviews'], ['search', 'Searches']]" :key="kind[0]"
            type="button" :class="{ on: historyKind === kind[0] }" :aria-pressed="historyKind === kind[0]"
            @click="historyKind = kind[0]">{{ t(kind[1]) }}</button>
        </div>
        <p v-if="historyError" class="notice error" role="alert">{{ t(historyError) }}</p>
        <p v-if="historyLoading" class="muted" role="status">{{ t('Loading history…') }}</p>
        <p v-else-if="!visibleHistory.length && !historyError" class="muted">{{ t('Your searches and reviews will appear here.') }}</p>
        <button v-for="item in visibleHistory" :key="item.id" type="button" class="history-item"
          :class="{ dim: item.kind === 'search' && !item.paper_count }"
          :disabled="!!openingHistory || !!busy" @click="openHistory(item.id)">
          <span class="icon" aria-hidden="true">{{ t(item.kind === 'review' ? '📄' : '🔍') }}</span>
          <span class="history-text">
            <strong>{{ item.topic }}</strong>
            <span class="muted">{{ t(item.kind === 'review' ? (item.output_mode === 'introduction' ? 'Introduction' : 'Review') : 'Search') }} ·
              {{ t(item.status === 'completed' ? (item.paper_count ? `${item.paper_count} papers` : 'no results') : item.status) }} ·
              {{ new Date(item.created_at).toLocaleString(locale) }}</span>
            <span v-if="openingHistory === item.id" class="muted">{{ t('Opening…') }}</span>
          </span>
        </button>
        <button v-if="historyHasMore" class="secondary" :disabled="historyLoading" @click="loadHistory(true)">{{ t('Load more') }}</button>
      </aside>
    </div>
    <footer>Literature Crew · arXiv + Semantic Scholar · {{ aiLabel }}</footer>
  </main>

  <div v-if="searched && papers.length" class="selection-bar">
    <div class="selection-inner">
      <div class="slots" aria-hidden="true">
        <span v-for="n in maxPapers" :key="n" :class="{ filled: n <= selected.length }"></span>
      </div>
      <strong class="badge">{{ selected.length }} / {{ maxPapers }} {{ t('selected') }}</strong>
      <span class="muted picked">{{ selectedPapers.map(shortCitation).join(' · ') }}</span>
      <span class="spacer"></span>
      <button class="secondary" type="button" :disabled="!!busy || !selected.length" @click="selected = []">{{ t('Clear') }}</button>
      <button :disabled="!!busy || !!activeReview || !configured || !selected.length" @click="generate">{{ t(generateLabel) }}</button>
    </div>
  </div>
</template>
