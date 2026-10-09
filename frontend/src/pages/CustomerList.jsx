import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Search, ChevronRight, ChevronLeft, Loader2, Play, AlertOctagon } from 'lucide-react'
import { getCustomers, generateRecommendations, getDataStatus } from '../api/client'

// Small confidence meter -- the single thing this whole list is ranked by.
function Confidence({ value }) {
  if (typeof value !== 'number') return <span className="text-gray-300 text-[12px]">—</span>
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-gray-300'
  const text = pct >= 70 ? 'text-emerald-700' : pct >= 40 ? 'text-amber-700' : 'text-gray-500'
  return (
    <div className="flex items-center gap-2 justify-end">
      <div className="w-20 h-1.5 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-[12px] font-bold tabular-nums w-9 text-right ${text}`}>{pct}%</span>
    </div>
  )
}

function CustomerRow({ c, index, onUpdate, canRun }) {
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState(null)

  const analyze = async (e) => {
    e.preventDefault(); e.stopPropagation()
    setAnalyzing(true); setError(null)
    try {
      const res = await generateRecommendations(c.customer_id)
      const r = res?.results?.find(x => x.customer_id === c.customer_id)
      if (r) onUpdate(c.customer_id, {
        analyzed: true,
        recommended_product: r.recommended_product,
        confidence: r.confidence,
        total_opportunity: r.revenue_opportunity,
        has_recommendation: !!r.recommended_product,
        is_low_confidence_pitch: r.is_low_confidence_pitch,
      })
    } catch (err) {
      setError(err?.response?.data?.detail || 'Analysis failed.')
    } finally {
      setAnalyzing(false)
    }
  }

  const current = c.current_product || c.plan_tier || '—'
  const analyzed = c.analyzed

  return (
    <motion.tr initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: index * 0.015 }}
      className="hover:bg-gray-50/50 transition-colors group">
      {/* Customer */}
      <td className="px-4 py-3">
        <Link to={`/customers/${c.customer_id}`} className="font-semibold text-[13px] text-gray-900 group-hover:text-blue-600 transition-colors">
          {c.company_name}
        </Link>
        {c.industry && c.industry !== 'Unknown' && <p className="text-[11px] text-gray-400 mt-0.5">{c.industry}</p>}
      </td>

      {/* Currently using */}
      <td className="px-4 py-3">
        <span className="text-[12px] text-gray-700">{current}</span>
      </td>

      {/* Recommended */}
      <td className="px-4 py-3">
        {analyzed && c.recommended_product ? (
          <div className="flex items-center gap-1.5">
            <span className="text-gray-300">→</span>
            <span className={`text-[12.5px] font-semibold ${c.is_low_confidence_pitch ? 'text-gray-500' : 'text-blue-700'}`}>
              {c.recommended_product}
            </span>
            {c.is_low_confidence_pitch && (
              <span className="text-[9px] font-bold uppercase text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">starting point</span>
            )}
          </div>
        ) : analyzed ? (
          <span className="text-[12px] text-gray-400 italic">No strong fit</span>
        ) : (
          <span className="text-[12px] text-gray-300 italic">Not analyzed</span>
        )}
      </td>

      {/* Potential */}
      <td className="px-4 py-3 text-right">
        {analyzed && c.total_opportunity > 0
          ? <span className="text-[12.5px] font-semibold text-gray-700 tabular-nums">${Math.round(c.total_opportunity).toLocaleString()}</span>
          : <span className="text-[12px] text-gray-300">—</span>}
      </td>

      {/* Confidence (the sort key) */}
      <td className="px-4 py-3"><Confidence value={analyzed ? c.confidence : undefined} /></td>

      {/* Action */}
      <td className="px-4 py-3 text-right">
        {analyzed ? (
          <Link to={`/customers/${c.customer_id}`} className="inline-flex opacity-0 group-hover:opacity-100 transition-opacity">
            <ChevronRight size={15} className="text-gray-400 group-hover:text-blue-500" />
          </Link>
        ) : (
          <button onClick={analyze} disabled={analyzing || !canRun} title={!canRun ? 'Upload a product catalog before running analysis' : undefined}
            className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-50 text-gray-700 text-[11px] font-semibold hover:bg-gray-100 border border-gray-200 transition-colors disabled:opacity-50 w-24">
            {analyzing ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} className="text-blue-600" />}
            {analyzing ? 'Running' : 'Analyze'}
          </button>
        )}
        {error && <p className="text-[10px] text-red-600 mt-1 max-w-[140px] text-right">{error}</p>}
      </td>
    </motion.tr>
  )
}

export default function CustomerList() {
  const [customers, setCustomers] = useState([])
  const [dataStatus, setDataStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const perPage = 15

  useEffect(() => {
    Promise.all([getCustomers(), getDataStatus()])
      .then(([c, d]) => { setCustomers(c); setDataStatus(d) })
      .finally(() => setLoading(false))
  }, [])
  const canRun = dataStatus?.can_run_analysis !== false

  const handleUpdate = (id, data) =>
    setCustomers(prev => prev.map(p => p.customer_id === id ? { ...p, ...data } : p))

  // The backend already returns customers ranked by confidence (nulls last);
  // preserve that order and only apply the text filter on top of it.
  const rows = useMemo(() => {
    if (!search) return customers
    const q = search.toLowerCase()
    return customers.filter(c => c.company_name?.toLowerCase().includes(q))
  }, [customers, search])

  const totalPages = Math.ceil(rows.length / perPage)
  const paged = rows.slice((page - 1) * perPage, page * perPage)
  const analyzedCount = customers.filter(c => c.analyzed).length

  if (loading) return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 w-48 skeleton" />
      <div className="h-12 skeleton" />
      <div className="h-96 skeleton" />
    </div>
  )

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-5">
      <div>
        <p className="text-[10px] font-extrabold uppercase tracking-[.2em] text-[#708075] mb-2">Portfolio intelligence / 02</p>
        <h1 className="text-[30px] sm:text-[34px] font-extrabold tracking-tight text-[#1a2923]">Your accounts<span className="text-[#7ba93c]">.</span></h1>
        <p className="text-[13px] text-[#718175] mt-1">
          Prioritized by recommendation confidence · {analyzedCount} of {customers.length} reviewed
        </p>
      </div>

      {dataStatus?.gaps?.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 mb-1.5">
            <AlertOctagon size={15} className="text-red-500" />
            <p className="text-[12.5px] font-bold text-red-800">Missing data</p>
          </div>
          <ul className="space-y-1">
            {dataStatus.gaps.map((g, i) => <li key={i} className="text-[12px] text-red-700">• {g}</li>)}
          </ul>
        </div>
      )}

      {/* Search only -- the ranking is the confidence score, no other sort/filter. */}
      <div className="relative max-w-xs">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}
          placeholder="Search companies…"
          className="w-full pl-9 pr-3 py-2 rounded-xl bg-white border border-gray-200 text-[13px] placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-lime-500/20 focus:border-lime-500" />
      </div>

      <div className="traject-card bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-gray-100">
                {['Customer', 'Currently using', 'We recommend', 'Potential', 'Confidence', ''].map((h, i) => (
                  <th key={i} className={`px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-gray-400 ${h === 'Potential' || h === 'Confidence' ? 'text-right' : 'text-left'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {paged.map((c, i) => (
                <CustomerRow key={c.customer_id} c={c} index={i} onUpdate={handleUpdate} canRun={canRun} />
              ))}
              {!paged.length && <tr><td colSpan={6} className="px-4 py-16 text-center text-[13px] text-gray-400">No customers match your search.</td></tr>}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="px-4 py-3 border-t border-gray-100 flex items-center justify-between text-[12px] text-gray-500">
            <span>Showing {(page - 1) * perPage + 1}–{Math.min(page * perPage, rows.length)} of {rows.length}</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="h-7 w-7 grid place-items-center rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-all" aria-label="Previous page">
                <ChevronLeft size={14} />
              </button>
              {(() => {
                const start = Math.min(Math.max(page - 1, 1), Math.max(1, totalPages - 2))
                return Array.from({ length: Math.min(3, totalPages) }, (_, i) => start + i)
              })().map(p => (
                <button key={p} onClick={() => setPage(p)}
                  className={`h-7 w-7 rounded-lg text-[11px] font-semibold transition-all ${page === p ? 'bg-[#1f4430] text-[#bdf583] shadow-sm' : 'hover:bg-gray-100 text-gray-500'}`}>{p}</button>
              ))}
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                className="h-7 w-7 grid place-items-center rounded-lg text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-all" aria-label="Next page">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
