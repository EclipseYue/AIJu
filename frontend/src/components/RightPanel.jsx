import { useEffect, useState } from 'react'
import {
  applyFeedback,
  chatRag,
  getRagStatus,
  getReportSummary,
  indexRag,
  listTextbooks,
  queryRag,
  queryScopedRag,
  runIntegration,
} from '../api/client.js'

const tabs = ['整合', 'RAG', '对话', '报告']

export function RightPanel({ selectedTextbookIds }) {
  const [activeTab, setActiveTab] = useState('RAG')

  return (
    <section className="section">
      <div className="tabs">
        {tabs.map((tab) => (
          <button
            className={activeTab === tab ? 'is-active' : ''}
            type="button"
            key={tab}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      {activeTab === 'RAG' && <RagPanel selectedTextbookIds={selectedTextbookIds} />}
      {activeTab === '整合' && <IntegrationPanel selectedTextbookIds={selectedTextbookIds} />}
      {activeTab === '对话' && <ChatPanel selectedTextbookIds={selectedTextbookIds} />}
      {activeTab === '报告' && <ReportPanel />}
    </section>
  )
}

function RagPanel({ selectedTextbookIds }) {
  const [status, setStatus] = useState(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function refreshStatus() {
    try {
      const data = await getRagStatus()
      setStatus(data)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refreshStatus()
  }, [])

  async function handleIndex() {
    setBusy(true)
    setMessage('')
    try {
      const result = await indexRag(selectedTextbookIds)
      setMessage(`索引完成：${result.chunk_count || 0} 个分块`)
      await refreshStatus()
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleQuery(event) {
    event.preventDefault()
    if (!question.trim()) return
    setBusy(true)
    setMessage('')
    try {
      const result = selectedTextbookIds.length > 0
        ? await queryScopedRag(question.trim(), selectedTextbookIds)
        : await queryRag(question.trim())
      setAnswer(result)
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel-body rag-panel">
      <div className="rag-header">
        <h2>RAG 问答</h2>
        <button type="button" disabled={busy} onClick={handleIndex}>
          {busy ? '索引中...' : '建立索引'}
        </button>
      </div>

      {status && (
        <div className="rag-status">
          <span>已索引 {status.indexed_textbooks} 本</span>
          <span>分块 {status.chunk_count}</span>
          <span>{status.status}</span>
        </div>
      )}

      {message && <div className="inline-message">{message}</div>}

      <form className="rag-form" onSubmit={handleQuery}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="输入问题，如：什么是内环境稳态？"
          rows={3}
        />
        <button type="submit" disabled={busy || !question.trim()}>
          {busy ? '查询中...' : '查询'}
        </button>
      </form>

      {answer && (
        <div className="rag-answer">
          <h3>回答</h3>
          <p>{answer.answer}</p>
          {answer.citations?.length > 0 && (
            <div className="citation-list">
              {answer.citations.map((cite, i) => (
                <div className="citation-item" key={i}>
                  <span>{cite.textbook}</span>
                  <small>{cite.chapter} · 相关度 {cite.relevance_score?.toFixed(2)}</small>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function IntegrationPanel({ selectedTextbookIds }) {
  const [decisions, setDecisions] = useState([])
  const [stats, setStats] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [feedbackInput, setFeedbackInput] = useState({})

  async function handleRun() {
    setBusy(true)
    setMessage('')
    try {
      if (selectedTextbookIds.length === 0) {
        setMessage('请先在左侧勾选已解析教材。')
        return
      }
      const result = await runIntegration(selectedTextbookIds)
      setDecisions(result.decisions || [])
      setStats(result)
      const ratio = (result.compression_ratio * 100).toFixed(1)
      setMessage(`整合完成，压缩比 ${ratio}%`)
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleFeedback(decisionId) {
    const msg = feedbackInput[decisionId]
    if (!msg?.trim()) return
    setBusy(true)
    try {
      const result = await applyFeedback(decisionId, msg.trim())
      setDecisions(result.decisions || [])
      setStats(result)
      setFeedbackInput((prev) => ({ ...prev, [decisionId]: '' }))
      setMessage('反馈已应用。')
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel-body">
      <div className="rag-header">
        <h2>跨教材整合</h2>
        <button type="button" disabled={busy} onClick={handleRun}>
          {busy ? '整合中...' : '运行整合'}
        </button>
      </div>

      {stats && (
        <div className="rag-status">
          <span>原始 {stats.original_chars} 字</span>
          <span>整合后 {stats.integrated_chars} 字</span>
          <span>压缩比 {(stats.compression_ratio * 100).toFixed(1)}%</span>
        </div>
      )}

      {message && <div className="inline-message">{message}</div>}

      <div className="decision-list">
        {decisions.length === 0 && <div className="empty-state">运行整合后显示决策列表</div>}
        {decisions.map((d) => (
          <details className="citation-item" key={d.decision_id}>
            <summary>
              <span>{d.action === 'merge' ? '合并' : d.action === 'keep' ? '保留' : '删除'}</span>
              <small>置信度 {d.confidence?.toFixed(2)}</small>
            </summary>
            <p>{d.reason}</p>
            <small>影响节点：{d.affected_nodes?.join(', ')}</small>
            <div className="feedback-row">
              <input
                value={feedbackInput[d.decision_id] || ''}
                onChange={(e) => setFeedbackInput((prev) => ({ ...prev, [d.decision_id]: e.target.value }))}
                placeholder="输入反馈（如：拆分、保留、恢复）"
              />
              <button type="button" disabled={busy} onClick={() => handleFeedback(d.decision_id)}>
                反馈
              </button>
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}

function ChatPanel({ selectedTextbookIds }) {
  const [history, setHistory] = useState([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')

  async function handleSend(event) {
    event.preventDefault()
    if (!message.trim()) return
    const userMsg = message.trim()
    setMessage('')
    setBusy(true)
    setStatusMsg('')
    try {
      const response = await chatRag(userMsg, history, selectedTextbookIds)
      setHistory(response.history || [])
      if (response.citations?.length) {
        setStatusMsg(`引用 ${response.citations.length} 个来源`)
      }
    } catch (err) {
      setStatusMsg(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel-body chat-panel">
      <h2>多轮对话</h2>
      <div className="chat-history">
        {history.length === 0 && <div className="empty-state">输入问题开始对话</div>}
        {history.map((msg, i) => (
          <div className={`chat-msg chat-${msg.role}`} key={i}>
            <strong>{msg.role === 'user' ? '教师' : 'AI'}</strong>
            <p>{msg.content}</p>
          </div>
        ))}
      </div>
      {statusMsg && <div className="inline-message">{statusMsg}</div>}
      <form className="rag-form" onSubmit={handleSend}>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="输入问题或反馈（如：把抗原和免疫原分开）"
          rows={3}
        />
        <button type="submit" disabled={busy || !message.trim()}>
          {busy ? '发送中...' : '发送'}
        </button>
      </form>
    </div>
  )
}

function ReportPanel() {
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleRefresh() {
    setBusy(true)
    try {
      const data = await getReportSummary()
      setReport(data)
    } catch (err) {
      // ignore
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    handleRefresh()
  }, [])

  return (
    <div className="panel-body">
      <div className="rag-header">
        <h2>整合报告</h2>
        <button type="button" disabled={busy} onClick={handleRefresh}>
          {busy ? '刷新中...' : '刷新'}
        </button>
      </div>

      {report ? (
        <div className="report-grid">
          <div className="report-item">
            <span className="report-label">教材数量</span>
            <span className="report-value">{report.textbook_count}</span>
          </div>
          <div className="report-item">
            <span className="report-label">原始总字数</span>
            <span className="report-value">{report.original_chars?.toLocaleString()}</span>
          </div>
          <div className="report-item">
            <span className="report-label">整合后字数</span>
            <span className="report-value">{report.integrated_chars?.toLocaleString()}</span>
          </div>
          <div className="report-item">
            <span className="report-label">压缩比</span>
            <span className="report-value">{(report.compression_ratio * 100).toFixed(1)}%</span>
          </div>
          <div className="report-item">
            <span className="report-label">合并决策</span>
            <span className="report-value">{report.merge_count}</span>
          </div>
          <div className="report-item">
            <span className="report-label">保留决策</span>
            <span className="report-value">{report.keep_count}</span>
          </div>
          <div className="report-item">
            <span className="report-label">删除决策</span>
            <span className="report-value">{report.remove_count}</span>
          </div>
        </div>
      ) : (
        <div className="empty-state">运行整合后生成报告</div>
      )}
    </div>
  )
}
