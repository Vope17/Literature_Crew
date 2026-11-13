<script setup>
import { t } from './i18n'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const preference = ref('system')
const media = window.matchMedia?.('(prefers-color-scheme: dark)')

function apply() {
  const root = document.documentElement
  root.dataset.themePreference = preference.value
  root.dataset.theme = preference.value === 'system' ? (media?.matches ? 'dark' : 'light') : preference.value
}

function change() {
  apply()
  try { localStorage.setItem('literature-theme', preference.value) }
  catch { /* The selected appearance still applies for this page. */ }
}

function sync(event) {
  if (event.key !== 'literature-theme') return
  preference.value = ['light', 'dark', 'system'].includes(event.newValue) ? event.newValue : 'system'
  apply()
}

onMounted(() => {
  try {
    const saved = localStorage.getItem('literature-theme')
    if (['light', 'dark', 'system'].includes(saved)) preference.value = saved
  } catch { /* Use the system appearance when storage is unavailable. */ }
  apply()
  media?.addEventListener('change', apply)
  window.addEventListener('storage', sync)
})
onBeforeUnmount(() => {
  media?.removeEventListener('change', apply)
  window.removeEventListener('storage', sync)
})
</script>

<template>
  <label class="theme-picker">{{ t('Appearance') }}
    <select v-model="preference" :aria-label="t('Appearance mode')" @change="change">
      <option value="system">{{ t('System') }}</option>
      <option value="light">{{ t('Light') }}</option>
      <option value="dark">{{ t('Dark') }}</option>
    </select>
  </label>
</template>
