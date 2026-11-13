import type { ReviewOptions, StudyField } from './types'

export const defaultReviewOptions = (): ReviewOptions => ({
  mode: 'review', language: 'zh-TW', title: '', motivation: '', research_question: '',
  objectives: '', context: '', units: '', method: '', contribution: '',
})

export const studyFields: [StudyField, string][] = [
  ['title', 'Working title'],
  ['motivation', 'Research motivation'],
  ['research_question', 'Research question'],
  ['objectives', 'Specific objectives'],
  ['context', 'Research context and setting'],
  ['units', 'Units of analysis'],
  ['method', 'Proposed method'],
  ['contribution', 'Expected contribution'],
]
