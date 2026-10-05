<script setup>
import { computed } from 'vue'

const props = defineProps({
  job: { type: Object, required: true },
  elapsed: { type: Number, default: 0 },
  canRetry: { type: Boolean, default: false },
})
defineEmits(['retry'])

// The backend reports free-text progress; map its known messages onto three steps.
const step = computed(() => {
  const message = props.job.progress || ''
  if (message.startsWith('Analysis complete')) return 2
  if (message.startsWith('Analyzing')) return 1
  return 0
})
const reading = computed(() => {
  const match = (props.job.progress || '').match(/^Reading paper (\d+)\/(\d+)/)
  return match ? { current: Number(match[1]), total: Number(match[2]) } : null
})
const papers = computed(() => props.job.papers || [])
const steps = computed(() => [
  {
    label: 'Read papers',
    detail: step.value > 0 ? `${papers.value.length || ''} done`.trim()
      : reading.value ? `${reading.value.current} / ${reading.value.total}` : 'Waiting…',
  },
  { label: 'Analyze evidence', detail: step.value === 1 ? 'In progress…' : step.value > 1 ? 'Done' : '' },
  { label: 'Write review', detail: step.value === 2 ? 'In progress…' : '' },
])
const elapsedLabel = computed(() => {
  const minutes = Math.floor(props.elapsed / 60)
  return minutes ? `${minutes}m ${props.elapsed % 60}s` : `${props.elapsed}s`
})

function paperState(index) {
  if (step.value > 0) return 'done'
  if (!reading.value) return 'waiting'
  if (index + 1 < reading.value.current) return 'done'
  return index + 1 === reading.value.current ? 'reading' : 'waiting'
}
</script>

<template>
  <section class="panel review-progress" aria-live="polite">
    <p class="muted eyebrow-line">Generating review<span v-if="elapsed"> · {{ elapsedLabel }} elapsed</span></p>
    <h2>{{ job.topic || 'Your topic' }}</h2>
    <ol class="steps">
      <li v-for="(item, i) in steps" :key="item.label" :class="{ done: i < step, now: i === step }">
        <strong>{{ i + 1 }}. {{ item.label }}</strong>
        <span class="muted">{{ item.detail }}</span>
      </li>
    </ol>
    <p class="notice progress" role="status"><span class="spinner"></span>{{ job.progress }}</p>
    <ul v-if="papers.length" class="reading-list">
      <li v-for="(paper, i) in papers" :key="paper.url" :class="paperState(i)">
        <span class="state" aria-hidden="true">
          <span v-if="paperState(i) === 'reading'" class="spinner small"></span>
          <template v-else>{{ paperState(i) === 'done' ? '✓' : '○' }}</template>
        </span>
        <span>P{{ i + 1 }} · {{ paper.title }}</span>
      </li>
    </ul>
    <p class="muted">You can keep searching while the review runs. Refreshing this page reconnects to it.</p>
    <button v-if="canRetry" class="secondary" @click="$emit('retry')">Retry status check</button>
  </section>
</template>
