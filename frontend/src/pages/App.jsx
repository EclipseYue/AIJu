import { useState } from 'react'
import { BookList } from '../components/BookList.jsx'
import { GraphCanvas } from '../components/GraphCanvas.jsx'
import { RightPanel } from '../components/RightPanel.jsx'

export default function App() {
  const [selectedTextbookIds, setSelectedTextbookIds] = useState([])

  return (
    <main className="shell">
      <aside className="sidebar">
        <header className="brand">
          <span className="brand-en">AIJu</span>
          <span className="brand-zh">爱聚学</span>
        </header>
        <p className="brand-subtitle">学科知识整合智能体</p>
        <BookList selectedIds={selectedTextbookIds} onSelectedIdsChange={setSelectedTextbookIds} />
      </aside>
      <section className="graph-region">
        <GraphCanvas selectedTextbookIds={selectedTextbookIds} />
      </section>
      <aside className="panel">
        <RightPanel selectedTextbookIds={selectedTextbookIds} />
      </aside>
    </main>
  )
}
