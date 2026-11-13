export type SourceKey = 'arxiv' | 'openalex' | 'semantic_scholar'

export interface SearchSource { value: SourceKey; label: string }
export interface SearchArea { value: string; label: string }

export interface Paper {
  title: string
  authors: string[]
  year: number
  url: string
  abstract: string
  /** Absent or null when no openly readable full text was found. */
  pdf_url?: string | null
  doi?: string | null
  source?: string
  journal?: string | null
  issn?: string[]
  publication_type?: string | null
  sources?: string[]
}

export interface SourceStatus { source: string; status: 'ok' | 'unavailable'; count: number }

export interface SearchFilters {
  area: string
  year_from: number | null
  year_to: number | null
  limit?: number
  sources?: SourceKey[]
}

export type FilterKey = 'area' | 'years' | 'limit'

export interface ReviewOptions {
  mode: 'review' | 'introduction'
  language: 'zh-TW' | 'en'
  title: string
  motivation: string
  research_question: string
  objectives: string
  context: string
  units: string
  method: string
  contribution: string
}
export type StudyField = Exclude<keyof ReviewOptions, 'mode' | 'language'>

export interface PageObservation { content_type: string; kind: string; text: string }
export interface PageReading {
  page: number
  part: number
  parts: number
  status: string
  limitations: string
  observations?: PageObservation[]
}

export interface EvidenceItem {
  id: string
  title: string
  year?: number
  url?: string
  coverage: string
  stored_pdf_url?: string | null
  page_count?: number
  processed_pages?: number
  batch_count?: number
  limited_pages?: number[]
  pages?: PageReading[]
}

export interface ReportCheck { name: string; status: string; details: string }

export interface ReviewJob {
  id: string
  status: string
  progress?: string
  topic?: string
  papers?: Paper[]
  created_at?: string
  error?: string
  review?: string
  evidence?: EvidenceItem[]
  checks?: ReportCheck[]
  options?: Partial<ReviewOptions>
  ai_backend?: string
  model?: string
  [key: string]: unknown
}

export interface SearchResponse {
  papers: Paper[]
  source?: string
  notice?: string | null
  keywords?: string[]
  filters?: SearchFilters
  source_status?: SourceStatus[]
  history_id?: string
}

export interface HistorySummary {
  id: string
  kind: 'search' | 'review'
  topic: string
  status: string
  created_at: string
  paper_count?: number
  output_mode?: string
}

export interface SavedHistory extends ReviewJob {
  kind: 'search' | 'review'
  topic: string
  papers: Paper[]
  source?: string
  notice?: string | null
  keywords?: string[]
  filters?: SearchFilters | null
}

export interface AppConfig {
  model: string
  has_api_key: boolean
  api_verified?: boolean
  ai_backend?: string
  ai_label?: string
  ready?: boolean
  connection_verified?: boolean
  connection_id?: string
  setup_hint?: string
  max_papers: number
  search_areas?: SearchArea[]
  search_sources?: SearchSource[]
}
