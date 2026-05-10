import cytoscape from 'cytoscape'
import { useEffect, useMemo, useRef, useState } from 'react'
import { buildGraph, getGraph, runIntegration } from '../api/client.js'

const categoryColor = {
  教材: '#0f766e',
  章节: '#2563eb',
  核心概念: '#b45309',
}

function colorFor(node) {
  if (node.category !== '核心概念') return categoryColor[node.category] || '#64748b'
  const palette = ['#b45309', '#7c3aed', '#dc2626', '#0891b2', '#4d7c0f', '#be185d']
  const seed = [...(node.textbook_id || '')].reduce((total, char) => total + char.charCodeAt(0), 0)
  return palette[seed % palette.length]
}

function elementsFromGraph(graph) {
  const nodes = graph.nodes.map((node) => {
    const size = node.category === '教材'
      ? 46
      : node.category === '章节'
        ? 34
        : Math.min(42, 22 + node.frequency * 4)
    return {
      data: {
        ...node,
        label: node.name,
        color: colorFor(node),
        size,
      },
    }
  })
  const edges = graph.edges.map((edge, index) => ({
    data: {
      id: `edge_${index}_${edge.source}_${edge.target}_${edge.relation_type}`,
      ...edge,
      label: edge.relation_type,
    },
  }))
  return [...nodes, ...edges]
}

export function GraphCanvas({ selectedTextbookIds }) {
  const containerRef = useRef(null)
  const cyRef = useRef(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [selectedNode, setSelectedNode] = useState(null)
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const stats = useMemo(() => ({
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    concepts: graph.nodes.filter((node) => node.category === '核心概念').length,
  }), [graph])

  useEffect(() => {
    getGraph()
      .then((nextGraph) => {
        if (nextGraph.nodes?.length) setGraph(nextGraph)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!containerRef.current) return undefined
    cyRef.current?.destroy()
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: elementsFromGraph(graph),
      minZoom: 0.18,
      maxZoom: 2.5,
      wheelSensitivity: 0.18,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            width: 'data(size)',
            height: 'data(size)',
            color: '#17202a',
            'font-size': 11,
            'text-wrap': 'wrap',
            'text-max-width': 92,
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 8,
            'border-width': 1,
            'border-color': '#ffffff',
          },
        },
        {
          selector: 'node[category = "教材"]',
          style: {
            color: '#0f3f3a',
            'font-weight': 700,
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1.4,
            label: 'data(label)',
            'font-size': 9,
            color: '#64748b',
            'line-color': '#94a3b8',
            'target-arrow-color': '#94a3b8',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
          },
        },
        {
          selector: 'edge[relation_type = "prerequisite"]',
          style: {
            'line-color': '#2563eb',
            'target-arrow-color': '#2563eb',
          },
        },
        {
          selector: 'edge[relation_type = "parallel"]',
          style: {
            'line-style': 'dashed',
            'line-color': '#b45309',
            'target-arrow-color': '#b45309',
          },
        },
        {
          selector: '.matched',
          style: {
            'border-width': 4,
            'border-color': '#facc15',
          },
        },
        {
          selector: '.faded',
          style: {
            opacity: 0.18,
          },
        },
      ],
      layout: {
        name: 'cose',
        animate: false,
        fit: true,
        padding: 42,
        nodeRepulsion: 9000,
        idealEdgeLength: 95,
      },
    })
    cyRef.current.on('tap', 'node', (event) => setSelectedNode(event.target.data()))
    cyRef.current.on('tap', (event) => {
      if (event.target === cyRef.current) setSelectedNode(null)
    })
    return () => cyRef.current?.destroy()
  }, [graph])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const keyword = search.trim().toLowerCase()
    cy.elements().removeClass('matched faded')
    if (!keyword) return
    const matched = cy.nodes().filter((node) => {
      const data = node.data()
      return `${data.name} ${data.definition} ${data.chapter || ''}`.toLowerCase().includes(keyword)
    })
    cy.nodes().difference(matched).addClass('faded')
    cy.edges().addClass('faded')
    matched.addClass('matched')
  }, [search, graph])

  async function handleBuildGraph() {
    setBusy(true)
    setMessage('')
    try {
      if (selectedTextbookIds.length === 0) {
        setMessage('请先在左侧勾选已解析教材。')
        return
      }
      const nextGraph = await buildGraph(selectedTextbookIds)
      setGraph(nextGraph)
      setMessage(`已构建 ${nextGraph.nodes.length} 个节点、${nextGraph.edges.length} 条关系。`)
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleIntegration() {
    setBusy(true)
    setMessage('')
    try {
      if (selectedTextbookIds.length === 0) {
        setMessage('请先在左侧勾选已解析教材。')
        return
      }
      const result = await runIntegration(selectedTextbookIds)
      if (result.graph?.nodes?.length) {
        setGraph(result.graph)
      }
      const ratio = (result.compression_ratio * 100).toFixed(1)
      setMessage(
        `整合完成：${result.decisions?.length || 0} 项决策，压缩比 ${ratio}%（目标 <=30%）`
      )
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="graph-canvas">
      <div className="graph-toolbar">
        <button type="button" disabled={busy} onClick={handleBuildGraph}>
          {busy ? '构建中...' : '构建图谱'}
        </button>
        <button type="button" disabled={busy} onClick={handleIntegration}>
          {busy ? '整合中...' : '运行整合'}
        </button>
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索知识点" />
      </div>

      <div className="graph-status">
        <span>节点 {stats.nodes}</span>
        <span>关系 {stats.edges}</span>
        <span>知识点 {stats.concepts}</span>
        {message && <strong>{message}</strong>}
      </div>

      <div className="graph-workspace">
        <div ref={containerRef} className="cytoscape-view" />
        {graph.nodes.length === 0 && (
          <div className="graph-empty">
            <span>Knowledge Graph</span>
            <p>上传并解析教材后，点击“构建图谱”。</p>
          </div>
        )}
        {selectedNode && (
          <aside className="node-detail">
            <strong>{selectedNode.name}</strong>
            <small>{selectedNode.category} · 频次 {selectedNode.frequency || 1}</small>
            <p>{selectedNode.definition || '暂无定义'}</p>
            <small>{selectedNode.textbook_title || '-'} / {selectedNode.chapter || '-'}</small>
            <small>页码：{selectedNode.page || '-'}</small>
          </aside>
        )}
      </div>
    </section>
  )
}
