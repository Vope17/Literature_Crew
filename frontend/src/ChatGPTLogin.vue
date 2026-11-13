<script setup>
import { t } from './i18n'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const emit = defineEmits(['connected'])
const state = ref({ status: 'checking', connected: false })
const busy = ref(false)
const error = ref('')
const copied = ref(false)
let timer
let alive = true
let controller
let sequence = 0

async function call(action = '') {
  controller?.abort()
  const current = new AbortController()
  controller = current
  const timeout = setTimeout(() => current.abort(), 30000)
  try {
    const response = await fetch(`/api/auth/chatgpt${action ? `/${action}` : ''}`, {
      method: action ? 'POST' : 'GET',
      ...(action ? { headers: { 'Content-Type': 'application/json' }, body: '{}' } : {}),
      cache: 'no-store', signal: current.signal,
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Unable to connect to ChatGPT.')
    return data
  } finally { clearTimeout(timeout) }
}

async function refresh() {
  clearTimeout(timer)
  const ticket = ++sequence
  try {
    const data = await call()
    if (!alive || ticket !== sequence) return
    state.value = data
    emit('connected', data.connected === true && data.status !== 'pending')
    error.value = ''
    if (data.status === 'pending') timer = setTimeout(refresh, 2000)
  } catch (err) {
    if (alive && ticket === sequence) error.value = err.message || 'Could not check ChatGPT sign-in. Retry the status check.'
  }
}

async function change(action) {
  const ticket = ++sequence
  clearTimeout(timer)
  busy.value = true
  error.value = ''
  copied.value = false
  try {
    const data = await call(action)
    if (!alive || ticket !== sequence) return
    state.value = data
    emit('connected', data.connected === true && data.status !== 'pending')
    if (data.status === 'pending') timer = setTimeout(refresh, 2000)
  } catch (err) {
    if (alive && ticket === sequence) error.value = err.message || 'Could not start ChatGPT sign-in. Please retry.'
  } finally { if (alive) busy.value = false }
}

async function copyCode() {
  try { await navigator.clipboard.writeText(state.value.user_code); copied.value = true }
  catch { error.value = 'Select and copy the code, then enter it on the OpenAI page.' }
}

onMounted(refresh)
onBeforeUnmount(() => { alive = false; clearTimeout(timer); controller?.abort() })
</script>

<template>
  <section class="chatgpt-login" :aria-label="t('ChatGPT subscription connection')" aria-live="polite">
    <p v-if="state.status === 'checking'" class="muted">{{ t('Checking ChatGPT connection…') }}</p>
    <p v-else-if="state.status === 'connected'" data-testid="chatgpt-connected">
      {{ t('Connected to ChatGPT') }}<span v-if="state.plan"> · {{ state.plan }}</span>
    </p>
    <template v-else-if="state.status === 'pending'">
      <p>{{ t('Enter this one-time code on the official OpenAI page:') }}</p>
      <p class="device-code"><code data-testid="device-code">{{ state.user_code }}</code>
        <button class="secondary" type="button" @click="copyCode">{{ t(copied ? 'Copied' : 'Copy code') }}</button>
      </p>
      <a class="auth-link" :href="state.verification_url" target="_blank" rel="noopener noreferrer">{{ t('Open OpenAI sign-in ↗') }}</a>
      <p class="muted">{{ t('Waiting for authorization. Sign in only on the official page; return here after approving.') }}</p>
      <button class="secondary" type="button" :disabled="busy" @click="change('cancel')">{{ t('Cancel sign-in') }}</button>
    </template>
    <template v-else-if="state.status !== 'checking'">
      <p v-if="state.message" class="notice warning">{{ t(state.message) }}</p>
      <button type="button" :disabled="busy" data-testid="chatgpt-connect" @click="change('start')">
        {{ t(busy ? 'Connecting…' : 'Connect ChatGPT subscription') }}
      </button>
      <p class="muted">{{ t('OpenAI may require device code login to be enabled in your ChatGPT security settings or workspace permissions.') }}</p>
    </template>
    <p v-if="error" role="alert" class="notice error">{{ t(error) }}</p>
    <button v-if="error || state.status === 'connected'" class="link" type="button" :disabled="busy" @click="refresh">{{ t('Retry status check') }}</button>
  </section>
</template>
