import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ReportView from './ReportView.vue'

it('shows visual page coverage, limitations and original page observations', () => {
  const wrapper = mount(ReportView, { props: { result: { review: '# Findings\nA figure [P1, p. 10].', evidence: [{
    id: 'P1', title: 'Visual paper', year: 2025, coverage: 'limited multimodal PDF',
    page_count: 12, processed_pages: 12, batch_count: 3, limited_pages: [11],
    pages: [
      { page: 10, part: 1, parts: 1, status: 'readable', limitations: '', observations: [{ content_type: 'figure', kind: 'reported', text: 'Accuracy rises with training size.' }] },
      { page: 11, part: 1, parts: 1, status: 'limited', limitations: 'Small table labels are illegible.', observations: [] },
    ],
  }] } } })
  expect(wrapper.text()).toContain('12/12 pages processed · 3 batches')
  expect(wrapper.text()).toContain('1 pages need review')
  expect(wrapper.text()).toContain('p. 10: readable')
  expect(wrapper.text()).toContain('Accuracy rises with training size.')
  expect(wrapper.text()).toContain('Small table labels are illegible.')
  expect(wrapper.get('.cov').classes()).toContain('warning')
  expect(wrapper.get('.cite').text()).toBe('P1, p. 10')
  wrapper.unmount()
})
