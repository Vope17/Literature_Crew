<script setup lang="ts">
import { t } from './i18n'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import type { EvidenceItem, ReviewJob } from './types'

const props = defineProps<{ result: ReviewJob }>()

const markdown = new MarkdownIt({ html: false, linkify: true })
// Give headings stable ids so the table of contents can link to them.
markdown.core.ruler.push('heading_ids', state => {
  let index = 0
  for (const token of state.tokens) {
    if (token.type === 'heading_open') token.attrSet('id', `section-${++index}`)
  }
})

const evidence = computed<EvidenceItem[]>(() => props.result.evidence || [])
const sourceIds = computed(() => new Set(evidence.value.map(item => item.id)))
const toc = computed(() => {
  const tokens = markdown.parse(props.result.review || '', {})
  const headings: { id: string; level: string; text: string }[] = []
  let index = 0
  tokens.forEach((token, i) => {
    if (token.type !== 'heading_open') return
    index += 1
    if (['h1', 'h2', 'h3'].includes(token.tag)) {
      headings.push({ id: `section-${index}`, level: token.tag, text: tokens[i + 1].content })
    }
  })
  return headings
})
const html = computed(() => {
  const rendered = markdown.render(props.result.review || '')
  // Keep the supplied page visible while linking the citation to source evidence.
  const linked = rendered.replace(/\[(P\d+(?:\s*[,;]\s*P\d+)*)(?:,\s*p\.\s*(\d+))?\]/g, (match: string, list: string, page?: string) => {
    const ids = list.split(/\s*[,;]\s*/)
    if (!ids.every(id => sourceIds.value.has(id))) return match
    return ids.map(id => `<a class="cite" href="#source-${id}">${id}${page ? `, p. ${page}` : ''}</a>`).join(' ')
  })
  return DOMPurify.sanitize(linked)
})

const tocOpen = ref(false)
const tocEl = ref<HTMLElement | null>(null)
const reportEl = ref<HTMLElement | null>(null)
// Only offer the floating contents button while the report is on screen.
const reportVisible = ref(true)
let observer: IntersectionObserver | undefined

function closeOnOutside(event: MouseEvent) {
  if (tocOpen.value && !tocEl.value?.contains(event.target as Node)) tocOpen.value = false
}
function closeOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') tocOpen.value = false
}

onMounted(() => {
  document.addEventListener('click', closeOnOutside)
  document.addEventListener('keydown', closeOnEscape)
  if (typeof IntersectionObserver === 'function' && reportEl.value) {
    observer = new IntersectionObserver(([entry]) => {
      reportVisible.value = entry.isIntersecting
      if (!entry.isIntersecting) tocOpen.value = false
    })
    observer.observe(reportEl.value)
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeOnOutside)
  document.removeEventListener('keydown', closeOnEscape)
  observer?.disconnect()
})

function download(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <section ref="reportEl" class="report">
    <div v-if="toc.length > 1" v-show="reportVisible" ref="tocEl" class="toc-float">
      <nav v-if="tocOpen" id="report-contents" class="toc" :aria-label="t('Contents')">
        <strong>{{ t('Contents') }}</strong>
        <a v-for="item in toc" :key="item.id" :href="`#${item.id}`" :class="item.level"
          @click="tocOpen = false">{{ item.text }}</a>
        <a href="#sources" @click="tocOpen = false">{{ t('Sources & coverage') }}</a>
      </nav>
      <button class="toc-toggle" type="button" :aria-expanded="tocOpen" aria-controls="report-contents"
        @click="tocOpen = !tocOpen">{{ t(tocOpen ? '✕ Close' : '☰ Contents') }}</button>
    </div>
    <article class="panel report-body">
      <div class="report-head">
        <h2>{{ t(result.options?.mode === 'introduction' ? `Introduction: ${result.topic}` : result.topic ? `Review: ${result.topic}` : 'Your literature review') }}</h2>
        <div class="downloads">
          <button class="secondary" @click="download(result.review ?? '', 'review.md', 'text/markdown')">Markdown ↓</button>
          <button class="secondary" @click="download(JSON.stringify(evidence, null, 2), 'evidence.json', 'application/json')">{{ t('Evidence JSON ↓') }}</button>
        </div>
      </div>
      <p class="muted">{{ t('Saved report') }}<span v-if="result.ai_backend"> · {{ result.ai_backend }}</span><span v-if="result.model"> · {{ result.model }}</span>{{ t('. Check claims against the original papers.') }}</p>

      <details v-if="result.checks?.length" class="report-checks">
        <summary>{{ t('Evidence checks') }} · {{ result.checks.filter(check => check.status === 'warning').length }} {{ t('need review') }}</summary>
        <ul>
          <li v-for="check in result.checks" :key="check.name" :class="check.status">
            <strong>{{ t(check.name) }}</strong>: {{ t(check.details) }}
          </li>
        </ul>
        <p class="muted">{{ t('These checks verify citation IDs, supplied page numbers and recorded coverage. Confirm claim support, visual interpretation and writing quality against the original papers.') }}</p>
      </details>

      <div v-if="evidence.length" id="sources" class="sources saved-pdfs">
        <h3>{{ t('Sources & coverage') }}</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>{{ t('Paper') }}</th><th>{{ t('Year') }}</th><th>{{ t('Coverage') }}</th><th>PDF</th></tr></thead>
            <tbody>
              <tr v-for="item in evidence" :id="`source-${item.id}`" :key="item.id">
                <td>{{ item.id }}</td>
                <td><a v-if="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
                  <template v-else>{{ item.title }}</template></td>
                <td>{{ item.year }}</td>
                <td><span class="cov" :class="['full PDF', 'multimodal PDF'].includes(item.coverage) ? 'full' : 'warning'">{{ t(item.coverage) }}</span>
                  <div v-if="item.page_count" class="muted">{{ item.processed_pages }}/{{ item.page_count }} {{ t('pages processed') }} · {{ item.batch_count }} {{ t('batches') }}</div>
                </td>
                <td><a v-if="item.stored_pdf_url" :href="item.stored_pdf_url" download>↓</a><span v-else class="muted">—</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <details v-for="item in evidence.filter(source => source.pages?.length)" :key="`pages-${item.id}`" class="report-checks">
          <summary>{{ item.id }} · {{ t('Page reading details') }}<span v-if="item.limited_pages?.length"> · {{ item.limited_pages.length }} {{ t('pages need review') }}</span></summary>
          <p class="muted">{{ t('Every page was submitted as text and a page image. Small labels, complex tables and formulas may still be misread. Full page notes are included in Evidence JSON.') }}</p>
          <ul>
            <li v-for="page in item.pages" :key="`${page.page}-${page.part}`" :class="page.status === 'readable' ? '' : 'warning'">
              <strong>{{ t('p.') }} {{ page.page }}<template v-if="page.parts > 1"> · {{ t('part') }} {{ page.part }}/{{ page.parts }}</template>: {{ t(page.status) }}</strong>
              <span v-if="page.limitations"> — {{ page.limitations }}</span>
              <ul v-if="page.observations?.length"><li v-for="(note, index) in page.observations" :key="index">[{{ t(note.content_type) }} · {{ t(note.kind) }}] {{ note.text }}</li></ul>
            </li>
          </ul>
        </details>
      </div>

      <div class="markdown" v-html="html"></div>
    </article>
  </section>
</template>
