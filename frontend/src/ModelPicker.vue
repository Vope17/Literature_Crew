<script setup>
import { t } from './i18n'
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  enabled: Boolean, disabled: Boolean, modelValue: { type: String, default: '' },
  defaultModel: { type: String, default: '' }, backend: { type: String, default: '' },
  connectionId: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'connection-error'])
const models = ref([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
let controller
let sequence = 0

async function load() {
  const ticket = ++sequence
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  error.value = ''
  const timeout = setTimeout(() => current.abort(), 30000)
  try {
    const query = props.connectionId ? `?${new URLSearchParams({ connection_id: props.connectionId })}` : ''
    const response = await fetch(`/api/models${query}`, { signal: current.signal, cache: 'no-store' })
    const data = await response.json()
    if (ticket !== sequence) return
    if (!response.ok) {
      if ([401, 403, 409].includes(response.status)) emit('connection-error', data.detail || 'Reconnect in settings.')
      throw new Error(data.detail || 'Could not load models.')
    }
    models.value = data.models || []
    notice.value = data.notice || ''
    if (props.modelValue && !models.value.some(item => item.id === props.modelValue)) emit('update:modelValue', '')
  } catch (err) {
    if (ticket === sequence) error.value = err.name === 'AbortError' ? 'Model lookup timed out. Please retry.' : err.message
  } finally {
    clearTimeout(timeout)
    if (ticket === sequence) loading.value = false
  }
}

watch(() => [props.enabled, props.backend, props.connectionId], ([enabled]) => {
  ++sequence
  controller?.abort()
  models.value = []
  error.value = ''
  notice.value = ''
  loading.value = false
  emit('update:modelValue', '')
  if (enabled) void load()
}, { immediate: true })
onBeforeUnmount(() => { ++sequence; controller?.abort() })
</script>

<template>
  <div v-if="enabled" class="model-picker">
    <label>{{ t('Model') }}
      <select :value="modelValue" data-testid="model-select" :disabled="loading || disabled"
        @change="emit('update:modelValue', $event.target.value)">
        <option value="">{{ t(defaultModel ? `Default (${defaultModel})` : 'Select a model') }}</option>
        <option v-for="item in models" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
    </label>
    <button class="link" type="button" :disabled="loading || disabled" @click="load">{{ t(loading ? 'Loading models…' : 'Refresh models') }}</button>
    <p v-if="error" class="notice error" role="alert">{{ t(error) }}</p>
    <p v-else-if="!loading && !models.length" class="muted">{{ t('No selectable models returned.') }}</p>
    <p v-if="notice" class="muted">{{ t(notice) }}</p>
  </div>
</template>
