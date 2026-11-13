<script setup lang="ts">
import { t } from './i18n'
import { onBeforeUnmount, onMounted, ref } from 'vue'

type Preference = 'system' | 'light' | 'dark'
const themes: readonly string[] = ['light', 'dark', 'system']
const preference = ref<Preference>('system')
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

function sync(event: StorageEvent) {
  if (event.key !== 'literature-theme') return
  preference.value = event.newValue !== null && themes.includes(event.newValue) ? event.newValue as Preference : 'system'
  apply()
}

onMounted(() => {
  try {
    const saved = localStorage.getItem('literature-theme')
    if (saved !== null && themes.includes(saved)) preference.value = saved as Preference
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
