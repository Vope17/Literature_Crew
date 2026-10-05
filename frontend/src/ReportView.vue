<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const props = defineProps({ result: { type: Object, required: true } })

const markdown = new MarkdownIt({ html: false, linkify: true })
// Give headings stable ids so the table of contents can link to them.
markdown.core.ruler.push('heading_ids', state => {
  let index = 0
  for (const token of state.tokens) {
    if (token.type === 'heading_open') token.attrSet('id', `section-${++index}`)
  }
})

const evidence = computed(() => props.result.evidence || [])
const sourceIds = computed(() => new Set(evidence.value.map(item => item.id)))
const toc = computed(() => {
  const tokens = markdown.parse(props.result.review || '', {})
  const headings = []
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
  // Turn citations such as [P1] or [P1, P2] into links to the coverage table.
  const linked = rendered.replace(/\[(P\d+(?:\s*[,;]\s*P\d+)*)\]/g, (match, list) => {
    const ids = list.split(/\s*[,;]\s*/)
    if (!ids.every(id => sourceIds.value.has(id))) return match
    return ids.map(id => `<a class="cite" href="#source-${id}">${id}</a>`).join(' ')
  })
  return DOMPurify.sanitize(linked)
})

const tocOpen = ref(false)
const tocEl = ref(null)
const reportEl = ref(null)
// Only offer the floating contents button while the report is on screen.
const reportVisible = ref(true)
let observer

function closeOnOutside(event) {
  if (tocOpen.value && !tocEl.value?.contains(event.target)) tocOpen.value = false
}
function closeOnEscape(event) {
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

function download(content, filename, type) {
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
      <nav v-if="tocOpen" id="report-contents" class="toc" aria-label="Contents">
        <strong>Contents</strong>
        <a v-for="item in toc" :key="item.id" :href="`#${item.id}`" :class="item.level"
          @click="tocOpen = false">{{ item.text }}</a>
        <a href="#sources" @click="tocOpen = false">Sources &amp; coverage</a>
      </nav>
      <button class="toc-toggle" type="button" :aria-expanded="tocOpen" aria-controls="report-contents"
        @click="tocOpen = !tocOpen">{{ tocOpen ? '✕ Close' : '☰ Contents' }}</button>
    </div>
    <article class="panel report-body">
      <div class="report-head">
        <h2>{{ result.topic ? `Review: ${result.topic}` : 'Your literature review' }}</h2>
        <div class="downloads">
          <button class="secondary" @click="download(result.review, 'review.md', 'text/markdown')">Markdown ↓</button>
          <button class="secondary" @click="download(JSON.stringify(evidence, null, 2), 'evidence.json', 'application/json')">Evidence JSON ↓</button>
        </div>
      </div>
      <p class="muted">Saved review<span v-if="result.model"> · {{ result.model }}</span>. Check claims against the original papers.</p>

      <div v-if="evidence.length" id="sources" class="sources saved-pdfs">
        <h3>Sources &amp; coverage</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Paper</th><th>Year</th><th>Coverage</th><th>PDF</th></tr></thead>
            <tbody>
              <tr v-for="item in evidence" :id="`source-${item.id}`" :key="item.id">
                <td>{{ item.id }}</td>
                <td><a v-if="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
                  <template v-else>{{ item.title }}</template></td>
                <td>{{ item.year }}</td>
                <td><span class="cov" :class="item.coverage === 'full PDF' ? 'full' : 'warning'">{{ item.coverage }}</span></td>
                <td><a v-if="item.stored_pdf_url" :href="item.stored_pdf_url" download>↓</a><span v-else class="muted">—</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="markdown" v-html="html"></div>
    </article>
  </section>
</template>
