import { useState, useCallback } from 'react'
import { uploadAndAnalyze } from '../api/client'

/* ── colour tokens ─────────────────────────────────────────────────── */
const accent      = '#6366f1'   // indigo-500
const accentHover = '#4f46e5'   // indigo-600
const green       = '#22c55e'
const amber       = '#f59e0b'
const rose        = '#f43f5e'
const slate100    = '#f1f5f9'
const slate200    = '#e2e8f0'
const slate600    = '#475569'
const slate800    = '#1e293b'

/* ── helper ────────────────────────────────────────────────────────── */
const pct = (v) => v != null ? `${v}%` : '—'
const usd = (v) => v != null ? `$${Number(v).toFixed(2)}` : '—'

export default function DatasetAnalysis() {
  const [file, setFile]           = useState(null)
  const [label, setLabel]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [result, setResult]       = useState(null)
  const [tab, setTab]             = useState('upsell')  // upsell | crossSell | summary | categories

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    const f = e.dataTransfer?.files?.[0]
    if (f) setFile(f)
  }, [])

  const handleAnalyze = async () => {
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const data = await uploadAndAnalyze(file, label)
      setResult(data)
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  /* ── Upload panel ─────────────────────────────────────────────── */
  const UploadPanel = () => (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => document.getElementById('file-input').click()}
        style={{
          border: `2px dashed ${file ? accent : slate200}`,
          borderRadius: 16,
          padding: '48px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          background: file ? '#eef2ff' : '#fff',
          transition: 'all .2s',
        }}
      >
        <input
          id="file-input"
          type="file"
          accept=".csv,.json,.jsonl,.xlsx,.xls,.tsv"
          style={{ display: 'none' }}
          onChange={(e) => setFile(e.target.files[0])}
        />
        <div style={{ fontSize: 48, marginBottom: 8 }}>📂</div>
        {file ? (
          <p style={{ color: accent, fontWeight: 600 }}>
            {file.name} ({(file.size / 1024).toFixed(0)} KB)
          </p>
        ) : (
          <p style={{ color: slate600 }}>
            Drop a CSV, JSON, JSONL, or Excel file here — or click to browse
          </p>
        )}
      </div>

      <div style={{ marginTop: 16 }}>
        <input
          type="text"
          placeholder="Dataset label (optional)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: 8,
            border: `1px solid ${slate200}`,
            fontSize: 14,
            boxSizing: 'border-box',
          }}
        />
      </div>

      <button
        onClick={handleAnalyze}
        disabled={!file || loading}
        style={{
          marginTop: 16,
          width: '100%',
          padding: '12px 0',
          borderRadius: 10,
          border: 'none',
          background: !file || loading ? slate200 : accent,
          color: !file || loading ? slate600 : '#fff',
          fontWeight: 600,
          fontSize: 15,
          cursor: !file || loading ? 'not-allowed' : 'pointer',
          transition: 'background .2s',
        }}
        onMouseEnter={(e) => { if (file && !loading) e.target.style.background = accentHover }}
        onMouseLeave={(e) => { if (file && !loading) e.target.style.background = accent }}
      >
        {loading ? '⏳ Analyzing…' : '🔍 Analyze for Upsell Opportunities'}
      </button>

      {error && (
        <div style={{
          marginTop: 12,
          padding: '10px 14px',
          borderRadius: 8,
          background: '#fef2f2',
          color: '#dc2626',
          fontSize: 13,
        }}>
          {error}
        </div>
      )}
    </div>
  )

  /* ── Summary cards ────────────────────────────────────────────── */
  const SummaryCards = () => {
    const ds = result.dataset_summary || {}
    const cards = [
      { label: 'Products',      value: ds.total_products || 0,       icon: '📦', color: accent  },
      { label: 'Reviews',       value: ds.total_reviews || 0,        icon: '⭐', color: amber   },
      { label: 'Relationships', value: ds.total_relationships || 0,  icon: '🔗', color: green   },
      { label: 'Categories',    value: ds.categories_count || 0,     icon: '🏷️', color: rose    },
      { label: 'Upsells Found', value: result.total_upsell || 0,     icon: '📈', color: green   },
      { label: 'Cross-Sells',   value: result.total_cross_sell || 0, icon: '🛒', color: accent  },
    ]
    return (
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: 12,
        marginBottom: 24,
      }}>
        {cards.map(c => (
          <div key={c.label} style={{
            background: '#fff',
            borderRadius: 12,
            padding: '16px 14px',
            boxShadow: '0 1px 3px rgba(0,0,0,.06)',
            borderLeft: `4px solid ${c.color}`,
          }}>
            <div style={{ fontSize: 24 }}>{c.icon}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: slate800 }}>{c.value}</div>
            <div style={{ fontSize: 12, color: slate600 }}>{c.label}</div>
          </div>
        ))}
      </div>
    )
  }

  /* ── Tabs ──────────────────────────────────────────────────────── */
  const tabs = [
    { key: 'upsell',     label: `📈 Upsell (${result?.total_upsell || 0})` },
    { key: 'crossSell',  label: `🛒 Cross-Sell (${result?.total_cross_sell || 0})` },
    { key: 'categories', label: '🏷️ Categories' },
    { key: 'summary',    label: '📊 Summary' },
  ]

  /* ── Opportunity table ────────────────────────────────────────── */
  const OpportunityTable = ({ opportunities, type }) => (
    <div style={{ overflowX: 'auto' }}>
      {opportunities.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 32, color: slate600 }}>
          No {type} opportunities found for this dataset.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: slate100, textAlign: 'left' }}>
              <th style={thStyle}>Score</th>
              <th style={thStyle}>Source Product</th>
              <th style={thStyle}>→</th>
              <th style={thStyle}>Target Product</th>
              <th style={thStyle}>Price Change</th>
              <th style={thStyle}>Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {opportunities.map((o, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${slate100}` }}>
                <td style={tdStyle}>
                  <span style={{
                    display: 'inline-block',
                    padding: '3px 10px',
                    borderRadius: 20,
                    fontWeight: 700,
                    fontSize: 12,
                    background: o.score >= 70 ? '#dcfce7' : o.score >= 40 ? '#fef3c7' : '#f1f5f9',
                    color: o.score >= 70 ? '#166534' : o.score >= 40 ? '#92400e' : slate600,
                  }}>
                    {o.score}
                  </span>
                </td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 600 }}>{o.source_title || o.source_product_id}</div>
                  <div style={{ fontSize: 11, color: slate600 }}>
                    {usd(o.source_price)} · {o.source_category || '—'}
                  </div>
                </td>
                <td style={{ ...tdStyle, fontSize: 18, textAlign: 'center' }}>→</td>
                <td style={tdStyle}>
                  <div style={{ fontWeight: 600 }}>{o.target_title || o.target_product_id}</div>
                  <div style={{ fontSize: 11, color: slate600 }}>
                    {usd(o.target_price)} · {o.target_category || '—'}
                  </div>
                </td>
                <td style={tdStyle}>
                  {type === 'upsell' && o.price_uplift != null
                    ? <span style={{ color: green, fontWeight: 600 }}>+{o.price_uplift}%</span>
                    : '—'}
                </td>
                <td style={{ ...tdStyle, maxWidth: 300, fontSize: 11, color: slate600 }}>
                  {o.reasoning}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )

  /* ── Category insights ────────────────────────────────────────── */
  const CategoryInsights = () => {
    const cats = result.category_insights || []
    return (
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
        {cats.map(c => (
          <div key={c.category} style={{
            background: '#fff',
            borderRadius: 12,
            padding: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,.06)',
          }}>
            <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>{c.category}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 12 }}>
              <span style={{ color: slate600 }}>Products</span>  <span style={{ fontWeight: 600 }}>{c.product_count}</span>
              <span style={{ color: slate600 }}>Avg Price</span> <span style={{ fontWeight: 600 }}>{usd(c.avg_price)}</span>
              <span style={{ color: slate600 }}>Avg Rating</span><span style={{ fontWeight: 600 }}>{c.avg_rating?.toFixed(1) || '—'}★</span>
              <span style={{ color: slate600 }}>Upsells</span>   <span style={{ fontWeight: 600, color: green }}>{c.upsell_opportunities}</span>
              <span style={{ color: slate600 }}>Cross-Sells</span><span style={{ fontWeight: 600, color: accent }}>{c.cross_sell_opportunities}</span>
            </div>
            {c.price_range && (
              <div style={{ marginTop: 6, fontSize: 11, color: slate600 }}>
                Price range: {usd(c.price_range[0])} – {usd(c.price_range[1])}
              </div>
            )}
          </div>
        ))}
        {cats.length === 0 && (
          <div style={{ textAlign: 'center', padding: 32, color: slate600 }}>No category data available.</div>
        )}
      </div>
    )
  }

  /* ── Dataset summary panel ────────────────────────────────────── */
  const DatasetSummary = () => {
    const ds = result.dataset_summary || {}
    const domain = result.domain || {}
    return (
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Domain Detection</h4>
          <p><strong>Domain:</strong> {domain.domain || '—'}</p>
          <p><strong>Confidence:</strong> {(domain.confidence * 100 || 0).toFixed(0)}%</p>
          <p><strong>Signal Matches:</strong> {JSON.stringify(domain.signal_matches || {})}</p>
        </div>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Price Distribution</h4>
          <p>Min: {usd(ds.price_range?.min)} · Max: {usd(ds.price_range?.max)}</p>
          <p>Mean: {usd(ds.price_range?.mean)} · Median: {usd(ds.price_range?.median)}</p>
        </div>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Ratings</h4>
          <p>Range: {ds.rating_range?.min?.toFixed(1)}★ – {ds.rating_range?.max?.toFixed(1)}★</p>
          <p>Mean: {ds.rating_range?.mean?.toFixed(2)}★</p>
        </div>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Relationship Graph</h4>
          <p>Nodes: {result.graph_stats?.nodes || 0} · Edges: {result.graph_stats?.edges || 0}</p>
          {result.graph_stats?.edge_type_counts && (
            <ul style={{ fontSize: 12, paddingLeft: 16, margin: '4px 0 0' }}>
              {Object.entries(result.graph_stats.edge_type_counts).map(([k, v]) => (
                <li key={k}>{k}: {v}</li>
              ))}
            </ul>
          )}
        </div>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Top Categories</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(ds.top_categories || []).map(c => (
              <span key={c} style={{
                padding: '2px 8px',
                borderRadius: 12,
                background: slate100,
                fontSize: 11,
              }}>{c}</span>
            ))}
          </div>
        </div>
        <div style={cardStyle}>
          <h4 style={cardTitleStyle}>Top Brands</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(ds.top_brands || []).map(b => (
              <span key={b} style={{
                padding: '2px 8px',
                borderRadius: 12,
                background: slate100,
                fontSize: 11,
              }}>{b}</span>
            ))}
          </div>
        </div>
      </div>
    )
  }

  /* ── Top products ─────────────────────────────────────────────── */
  const TopProducts = () => {
    const prods = result.top_products || []
    if (prods.length === 0) return null
    return (
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>🏆 Top Products</h3>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 10,
        }}>
          {prods.slice(0, 6).map(p => (
            <div key={p.product_id} style={{
              background: '#fff',
              borderRadius: 10,
              padding: 12,
              boxShadow: '0 1px 3px rgba(0,0,0,.06)',
            }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{p.title || p.product_id}</div>
              <div style={{ fontSize: 11, color: slate600 }}>
                {usd(p.price)} · {p.avg_rating?.toFixed(1)}★ · {p.review_count} reviews
              </div>
              <div style={{ fontSize: 11, color: slate600 }}>{p.category} · {p.brand}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  /* ── main render ──────────────────────────────────────────────── */
  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
        📊 Universal Dataset Analysis
      </h1>
      <p style={{ color: slate600, fontSize: 14, marginBottom: 24 }}>
        Upload any product dataset (Amazon UCSD, e-commerce CSV, etc.) and discover upsell &amp; cross-sell opportunities.
      </p>

      {!result && <UploadPanel />}

      {result && result.status === 'complete' && (
        <>
          {/* Reset button */}
          <button
            onClick={() => { setResult(null); setFile(null); setLabel('') }}
            style={{
              marginBottom: 16,
              padding: '6px 14px',
              borderRadius: 8,
              border: `1px solid ${slate200}`,
              background: '#fff',
              color: slate600,
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            ← Upload another dataset
          </button>

          <SummaryCards />
          <TopProducts />

          {/* Tab bar */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
            {tabs.map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={{
                  padding: '8px 16px',
                  borderRadius: 8,
                  border: 'none',
                  background: tab === t.key ? accent : '#fff',
                  color: tab === t.key ? '#fff' : slate600,
                  fontWeight: tab === t.key ? 700 : 500,
                  fontSize: 13,
                  cursor: 'pointer',
                  boxShadow: tab === t.key ? 'none' : '0 1px 2px rgba(0,0,0,.06)',
                  transition: 'all .15s',
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={{
            background: '#fff',
            borderRadius: 12,
            padding: 20,
            boxShadow: '0 1px 4px rgba(0,0,0,.05)',
          }}>
            {tab === 'upsell' && (
              <OpportunityTable opportunities={result.upsell_opportunities || []} type="upsell" />
            )}
            {tab === 'crossSell' && (
              <OpportunityTable opportunities={result.cross_sell_opportunities || []} type="cross-sell" />
            )}
            {tab === 'categories' && <CategoryInsights />}
            {tab === 'summary' && <DatasetSummary />}
          </div>
        </>
      )}
    </div>
  )
}

/* ── shared styles ─────────────────────────────────────────────────── */
const thStyle = { padding: '10px 12px', fontWeight: 600, fontSize: 12, color: '#475569' }
const tdStyle = { padding: '10px 12px', verticalAlign: 'top' }
const cardStyle = {
  background: '#fff',
  borderRadius: 12,
  padding: 16,
  boxShadow: '0 1px 3px rgba(0,0,0,.06)',
}
const cardTitleStyle = { fontSize: 14, fontWeight: 700, marginBottom: 8, marginTop: 0 }
