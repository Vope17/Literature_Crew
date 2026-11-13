<script setup>
import { onMounted } from 'vue'
import { locale, t, setLocale, loadLocale } from './i18n'
onMounted(loadLocale)
</script>

<template>
  <label>{{ t('Interface language') }}
    <select :value="locale" data-testid="interface-language" :aria-label="t('Interface language')"
      @change="setLocale($event.target.value)">
      <option value="en">English</option>
      <option value="zh-TW">繁體中文</option>
    </select>
  </label>
</template>
