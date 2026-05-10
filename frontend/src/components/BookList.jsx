import { useEffect, useRef, useState } from 'react'
import { cleanupTextbooks, listTextbooks, parseTextbook, uploadTextbook } from '../api/client.js'

const statusLabel = {
  pending: '待解析',
  parsing: '解析中',
  completed: '已完成',
  failed: '失败',
}

function formatBytes(bytes = 0) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export function BookList({ selectedIds, onSelectedIdsChange }) {
  const inputRef = useRef(null)
  const [books, setBooks] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function refreshBooks(nextSelectedIds = selectedIds) {
    const nextBooks = await listTextbooks()
    setBooks(nextBooks)
    const availableIds = new Set(nextBooks.map((book) => book.textbook_id))
    const cleanedSelection = nextSelectedIds.filter((id) => availableIds.has(id))
    if (cleanedSelection.length !== nextSelectedIds.length) {
      onSelectedIdsChange(cleanedSelection)
    }
  }

  useEffect(() => {
    refreshBooks().catch((err) => setError(err.message))
  }, [])

  function toggleSelection(textbookId) {
    if (selectedIds.includes(textbookId)) {
      onSelectedIdsChange(selectedIds.filter((id) => id !== textbookId))
    } else {
      onSelectedIdsChange([...selectedIds, textbookId])
    }
  }

  async function handleFiles(files) {
    const selectedFiles = Array.from(files || [])
    if (selectedFiles.length === 0) return
    setBusy(true)
    setError('')
    try {
      const uploadedIds = []
      for (const file of selectedFiles) {
        const uploaded = await uploadTextbook(file)
        uploadedIds.push(uploaded.textbook_id)
      }
      const nextSelection = Array.from(new Set([...selectedIds, ...uploadedIds]))
      onSelectedIdsChange(nextSelection)
      await refreshBooks(nextSelection)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function handleParse(textbookId) {
    setBusy(true)
    setError('')
    try {
      const parsed = await parseTextbook(textbookId)
      setBooks((current) => current.map((book) => (book.textbook_id === textbookId ? parsed : book)))
      if (!selectedIds.includes(textbookId)) {
        onSelectedIdsChange([...selectedIds, textbookId])
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleCleanup() {
    setBusy(true)
    setError('')
    try {
      const result = await cleanupTextbooks()
      await refreshBooks([])
      onSelectedIdsChange([])
      setError(`已清理 ${result.removed_records} 条重复记录、${result.removed_files} 个缓存/重复文件。`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const selectedBook = books.find((book) => selectedIds.includes(book.textbook_id)) || books[0]

  return (
    <section className="section book-manager">
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept=".pdf,.md,.markdown,.txt,.docx,.xlsx"
        multiple
        onChange={(event) => handleFiles(event.target.files)}
      />
      <button
        className="upload-box"
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          handleFiles(event.dataTransfer.files)
        }}
      >
        <span>{busy ? '处理中...' : '拖拽或点击上传教材'}</span>
        <small>重复文件会按内容哈希自动复用</small>
      </button>

      <div className="book-actions">
        <button type="button" disabled={busy} onClick={handleCleanup}>清理重复与缓存</button>
        <small>已选 {selectedIds.length} 本</small>
      </div>

      {error && <div className={error.startsWith('已清理') ? 'inline-message' : 'error-box'}>{error}</div>}

      <div className="book-list">
        {books.length === 0 && <div className="empty-state">尚未上传教材</div>}
        {books.map((book) => (
          <article
            className={`book-row ${selectedIds.includes(book.textbook_id) ? 'is-selected' : ''}`}
            key={book.textbook_id}
          >
            <label className="book-select">
              <input
                type="checkbox"
                checked={selectedIds.includes(book.textbook_id)}
                onChange={() => toggleSelection(book.textbook_id)}
              />
              <span>
                <strong>{book.filename}</strong>
                <small>
                  {book.file_format.toUpperCase()} · {formatBytes(book.size_bytes)} · {statusLabel[book.parse_status] || book.parse_status}
                </small>
              </span>
            </label>
            <button
              type="button"
              className="parse-button"
              disabled={busy || book.parse_status === 'completed'}
              onClick={() => handleParse(book.textbook_id)}
            >
              {book.parse_status === 'completed' ? '已解析' : '解析'}
            </button>
          </article>
        ))}
      </div>

      {selectedBook && (
        <section className="chapter-panel">
          <div className="chapter-summary">
            <strong>{selectedBook.title}</strong>
            <small>
              {selectedBook.total_pages || '-'} 页 · {selectedBook.total_chars || 0} 字 · {selectedBook.chapters.length} 章
            </small>
          </div>
          <div className="chapter-list">
            {selectedBook.chapters.length === 0 && <div className="empty-state">解析后显示章节</div>}
            {selectedBook.chapters.map((chapter) => (
              <div className="chapter-row" key={chapter.chapter_id}>
                <span>{chapter.title}</span>
                <small>
                  页码 {chapter.page_start || '-'}-{chapter.page_end || '-'} · {chapter.char_count} 字
                </small>
              </div>
            ))}
          </div>
        </section>
      )}
    </section>
  )
}
