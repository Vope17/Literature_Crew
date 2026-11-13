<script setup lang="ts">
import { t } from './i18n'
import { studyFields } from './reviewOptions'
import type { ReviewOptions } from './types'

const props = defineProps<{ modelValue: ReviewOptions; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReviewOptions] }>()
function update<K extends keyof ReviewOptions>(key: K, value: ReviewOptions[K]) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
const field = (event: Event) => (event.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value
</script>

<template>
  <section class="panel writing-options" :aria-label="t('Report options')">
    <h2>{{ t('Report options') }}</h2>
    <p class="muted">{{ t('Reads each PDF as page text and images in batches. Choose a vision-capable model; longer papers require more time and AI usage.') }}</p>
    <div class="option-row">
      <label>{{ t('Output') }}
        <select :value="modelValue.mode" :disabled="disabled" data-testid="output-mode"
          @change="update('mode', field($event) as ReviewOptions['mode'])">
          <option value="review">{{ t('Literature review') }}</option>
          <option value="introduction">{{ t('Introduction draft') }}</option>
        </select>
      </label>
      <label>{{ t('Language') }}
        <select :value="modelValue.language" :disabled="disabled" data-testid="output-language"
          @change="update('language', field($event) as ReviewOptions['language'])">
          <option value="zh-TW">繁體中文</option>
          <option value="en">English</option>
        </select>
      </label>
    </div>
    <p v-if="modelValue.mode === 'review'" class="muted">{{ t('Synthesizes themes, agreements, opposing findings and candidate research gaps across your selected papers.') }}</p>
    <template v-else>
      <p class="muted">{{ t('Describe your own proposed study. Missing details will be marked “待補 / To supply” in the draft.') }}</p>
      <div class="study-fields">
        <label v-for="[key, label] in studyFields" :key="key">{{ t(label) }}
          <textarea :value="modelValue[key]" :data-testid="`study-${key}`" :disabled="disabled"
            :maxlength="key === 'title' ? 2000 : 3000" rows="2"
            @input="update(key, field($event))"></textarea>
        </label>
      </div>
    </template>
  </section>
</template>
