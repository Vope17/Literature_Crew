<script setup>
import { studyFields } from './reviewOptions'

const props = defineProps({ modelValue: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
function update(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <section class="panel writing-options" aria-label="Report options">
    <h2>Report options</h2>
    <div class="option-row">
      <label>Output
        <select :value="modelValue.mode" :disabled="disabled" data-testid="output-mode"
          @change="update('mode', $event.target.value)">
          <option value="review">Literature review</option>
          <option value="introduction">Introduction draft</option>
        </select>
      </label>
      <label>Language
        <select :value="modelValue.language" :disabled="disabled" data-testid="output-language"
          @change="update('language', $event.target.value)">
          <option value="zh-TW">繁體中文</option>
          <option value="en">English</option>
        </select>
      </label>
    </div>
    <p v-if="modelValue.mode === 'review'" class="muted">Synthesizes themes, agreements, opposing findings and candidate research gaps across your selected papers.</p>
    <template v-else>
      <p class="muted">Describe your own proposed study. Missing details will be marked “待補 / To supply” in the draft.</p>
      <div class="study-fields">
        <label v-for="[key, label] in studyFields" :key="key">{{ label }}
          <textarea :value="modelValue[key]" :data-testid="`study-${key}`" :disabled="disabled"
            :maxlength="key === 'title' ? 2000 : 3000" rows="2"
            @input="update(key, $event.target.value)"></textarea>
        </label>
      </div>
    </template>
  </section>
</template>
