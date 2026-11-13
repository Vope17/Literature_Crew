import type { Paper, SearchSource, SourceKey } from './types'

/** Used until /api/config reports the sources the backend supports. */
export const DEFAULT_SOURCES: SearchSource[] = [
  { value: 'openalex', label: 'OpenAlex' },
  { value: 'semantic_scholar', label: 'Semantic Scholar' },
  { value: 'arxiv', label: 'arXiv' },
]

export const SOURCE_STORAGE_KEY = 'literature-sources'

export function isArxivUrl(url: string): boolean {
  try { return new URL(url).hostname === 'arxiv.org' } catch { return false }
}

/** Catalogs that returned this paper; older saved records only carry `source` or an arXiv link. */
export function paperSources(paper: Paper): string[] {
  if (paper.sources?.length) return paper.sources
  if (paper.source) return [paper.source]
  return isArxivUrl(paper.url) ? ['arXiv'] : []
}

export function hasOpenFullText(paper: Paper): boolean {
  return !!paper.pdf_url
}

export function doiText(paper: Paper): string | null {
  const doi = paper.doi?.trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, '')
  return doi || null
}

export function doiUrl(paper: Paper): string | null {
  const doi = doiText(paper)
  return doi ? `https://doi.org/${doi.split('/').map(encodeURIComponent).join('/')}` : null
}

export function paperLinkLabel(paper: Paper): string {
  return isArxivUrl(paper.url) ? 'View on arXiv ↗' : 'View paper ↗'
}

/** Drops unknown keys and duplicates; falls back to every available source. */
export function normalizeSources(saved: unknown, available: SearchSource[]): SourceKey[] {
  const allowed = available.map(item => item.value)
  const picked = Array.isArray(saved) ? allowed.filter(key => saved.includes(key)) : []
  return picked.length ? picked : allowed
}

/** "JournalArticle, Review" -> "Journal Article, Review"; unknown shapes stay readable. */
export function publicationTypeLabel(type: string | null | undefined): string {
  if (!type) return ''
  return type.split(',').map(part => {
    const words = part.trim().replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2')
    return words.charAt(0).toUpperCase() + words.slice(1)
  }).filter(Boolean).join(', ')
}
