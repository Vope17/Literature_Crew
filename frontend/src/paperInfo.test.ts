import { expect, it } from 'vitest'
import {
  DEFAULT_SOURCES, doiText, doiUrl, hasOpenFullText, isArxivUrl, normalizeSources, paperLinkLabel,
  paperSources, publicationTypeLabel,
} from './paperInfo'
import type { Paper } from './types'

const base: Paper = { title: 'T', authors: [], year: 2025, url: 'https://doi.org/10.1/x', abstract: '' }

it('names the catalogs of a paper, including records saved before multi-source search', () => {
  expect(paperSources({ ...base, sources: ['arXiv', 'OpenAlex'], source: 'arXiv' })).toEqual(['arXiv', 'OpenAlex'])
  expect(paperSources({ ...base, source: 'Semantic Scholar' })).toEqual(['Semantic Scholar'])
  expect(paperSources({ ...base, url: 'https://arxiv.org/abs/2501.00001' })).toEqual(['arXiv'])
  expect(paperSources(base)).toEqual([])
})

it('recognises arXiv links only by their exact host', () => {
  expect(isArxivUrl('https://arxiv.org/abs/1')).toBe(true)
  expect(isArxivUrl('https://arxiv.org.evil.example/abs/1')).toBe(false)
  expect(isArxivUrl('not a url')).toBe(false)
  expect(paperLinkLabel({ ...base, url: 'https://arxiv.org/abs/1' })).toBe('View on arXiv ↗')
  expect(paperLinkLabel(base)).toBe('View paper ↗')
})

it('reports open full text only when a PDF link exists', () => {
  expect(hasOpenFullText({ ...base, pdf_url: 'https://repo.example/a.pdf' })).toBe(true)
  expect(hasOpenFullText({ ...base, pdf_url: null })).toBe(false)
  expect(hasOpenFullText(base)).toBe(false)
})

it('builds a DOI link without trusting the stored prefix or characters', () => {
  expect(doiText({ ...base, doi: ' https://doi.org/10.1234/Abc ' })).toBe('10.1234/Abc')
  expect(doiUrl({ ...base, doi: 'doi: 10.1234/a b#c' })).toBe('https://doi.org/10.1234/a%20b%23c')
  expect(doiUrl({ ...base, doi: null })).toBeNull()
  expect(doiUrl(base)).toBeNull()
})

it('keeps saved source choices valid and falls back to every source', () => {
  expect(normalizeSources(['arxiv', 'nope', 'openalex'], DEFAULT_SOURCES)).toEqual(['openalex', 'arxiv'])
  expect(normalizeSources(['nope'], DEFAULT_SOURCES)).toEqual(['openalex', 'semantic_scholar', 'arxiv'])
  expect(normalizeSources(null, DEFAULT_SOURCES)).toEqual(['openalex', 'semantic_scholar', 'arxiv'])
  expect(normalizeSources('arxiv', DEFAULT_SOURCES)).toEqual(['openalex', 'semantic_scholar', 'arxiv'])
})

it('makes publication types readable', () => {
  expect(publicationTypeLabel('JournalArticle, Review')).toBe('Journal Article, Review')
  expect(publicationTypeLabel('article')).toBe('Article')
  expect(publicationTypeLabel('book-chapter')).toBe('Book chapter')
  expect(publicationTypeLabel(null)).toBe('')
})
