// In production (same-origin deployment), VITE_API_BASE is empty.
// In local dev, it's http://localhost:8000.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function apiGet(path) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`)
  }
  return response.json()
}

export async function apiPost(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`)
  }
  return response.json()
}

export async function uploadTextbook(file) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE}/api/textbooks/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) {
    throw new Error(`Upload failed: ${response.status}`)
  }
  return response.json()
}

export function listTextbooks() {
  return apiGet('/api/textbooks')
}

export function parseTextbook(textbookId) {
  return apiPost(`/api/textbooks/${textbookId}/parse`, { force: false })
}

export function cleanupTextbooks() {
  return apiPost('/api/textbooks/cleanup', {})
}

export function buildGraph(textbookIds, maxChaptersPerBook = 8) {
  return apiPost('/api/graph/build', {
    textbook_ids: textbookIds,
    max_chapters_per_book: maxChaptersPerBook,
  })
}

export function getGraph() {
  return apiGet('/api/graph')
}

export function getRagStatus() {
  return apiGet('/api/rag/status')
}

export function indexRag(textbookIds, chunkSize = 650, overlapSize = 80) {
  return apiPost('/api/rag/index', {
    textbook_ids: textbookIds,
    chunk_size: chunkSize,
    overlap_size: overlapSize,
  })
}

export function queryRag(question, topK = 5) {
  return apiPost('/api/rag/query', {
    question,
    top_k: topK,
  })
}

export function queryScopedRag(question, textbookIds, topK = 5) {
  return apiPost('/api/rag/query', {
    question,
    textbook_ids: textbookIds,
    top_k: topK,
  })
}

export function chatRag(message, history, textbookIds, topK = 5) {
  return apiPost('/api/rag/chat', {
    message,
    history,
    textbook_ids: textbookIds,
    top_k: topK,
  })
}

export function runIntegration(textbookIds, compressionTarget = 0.3) {
  return apiPost('/api/integration/run', {
    textbook_ids: textbookIds,
    compression_target: compressionTarget,
  })
}

export function applyFeedback(decisionId, message, sessionId = 'default') {
  return apiPost('/api/integration/feedback', {
    session_id: sessionId,
    decision_id: decisionId,
    message,
  })
}

export function getReportSummary() {
  return apiGet('/api/report/summary')
}
