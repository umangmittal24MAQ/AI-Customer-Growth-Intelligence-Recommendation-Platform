import { useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getAnalyticsSummary } from '../api/client'

const SEGMENTS = ['HIGH', 'MEDIUM', 'LOW']

export default function RecommendationsTracking() {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getAnalyticsSummary().then(setSummary).finally(() => setLoading(false))
  }, [])

  const { chartData, totals } = useMemo(() => {
    const funnel = summary?.conversion_funnel || []
    const bySegment = {}
    const totals = { recommended: 0, accepted: 0, rejected: 0, pending: 0 }
    SEGMENTS.forEach((s) => { bySegment[s] = { segment: s, recommended: 0, accepted: 0, rejected: 0, pending: 0 } })
    funnel.forEach((row) => {
      const seg = row.segment
      if (!bySegment[seg]) return
      bySegment[seg].recommended += row.count
      bySegment[seg][row.status] = (bySegment[seg][row.status] || 0) + row.count
      totals.recommended += row.count
      totals[row.status] = (totals[row.status] || 0) + row.count
    })
    return { chartData: SEGMENTS.map((s) => bySegment[s]), totals }
  }, [summary])

  if (loading) return <div className="flex items-center justify-center h-40 text-sm text-slate-400">Loading tracking…</div>

  const acceptRate = totals.recommended ? Math.round((totals.accepted / totals.recommended) * 100) : 0

  const stats = [
    { label: 'Total recommended', value: totals.recommended, color: 'text-slate-900', sub: 'Across all segments' },
    { label: 'Accepted', value: totals.accepted, color: 'text-emerald-600', sub: 'By account managers' },
    { label: 'Rejected', value: totals.rejected, color: 'text-red-600', sub: 'Not actionable' },
    { label: 'Accept rate', value: `${acceptRate}%`, color: 'text-brand-600', sub: 'Conversion efficiency' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-900">Recommendations Tracking</h1>
        <p className="text-sm text-slate-500 mt-0.5">Conversion funnel — recommended vs accepted vs rejected</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="card card-body">
            <p className="section-title">{s.label}</p>
            <p className={`stat-value mt-1 ${s.color}`}>{s.value}</p>
            <p className="text-[11px] text-slate-400 mt-1">{s.sub}</p>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="card">
        <div className="card-header">
          <h3 className="text-sm font-semibold text-slate-900">Conversion funnel by segment</h3>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-slate-300" />Pending</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />Accepted</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" />Rejected</span>
          </div>
        </div>
        <div className="card-body">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={chartData} barCategoryGap="20%">
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="segment" tick={{ fontSize: 12, fill: '#64748b' }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 12, boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.05)' }}
              />
              <Bar dataKey="pending" stackId="a" fill="#cbd5e1" name="Pending" radius={[0, 0, 0, 0]} />
              <Bar dataKey="accepted" stackId="a" fill="#22c55e" name="Accepted" radius={[0, 0, 0, 0]} />
              <Bar dataKey="rejected" stackId="a" fill="#ef4444" name="Rejected" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Breakdown table */}
      <div className="card overflow-hidden">
        <div className="card-header">
          <h3 className="text-sm font-semibold text-slate-900">Segment breakdown</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-100">
                <th className="text-left font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Segment</th>
                <th className="text-right font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Recommended</th>
                <th className="text-right font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Accepted</th>
                <th className="text-right font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Rejected</th>
                <th className="text-right font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Pending</th>
                <th className="text-right font-semibold text-slate-500 text-xs uppercase tracking-wider px-5 py-3">Accept rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {chartData.map((row) => {
                const rate = row.recommended ? Math.round((row.accepted / row.recommended) * 100) : 0
                const segBadge = row.segment === 'HIGH' ? 'badge-danger' : row.segment === 'MEDIUM' ? 'badge-warning' : 'badge-success'
                return (
                  <tr key={row.segment} className="hover:bg-slate-50/50">
                    <td className="px-5 py-3.5"><span className={`badge ${segBadge}`}>{row.segment}</span></td>
                    <td className="px-5 py-3.5 text-right font-semibold text-slate-700 tabular-nums">{row.recommended}</td>
                    <td className="px-5 py-3.5 text-right text-emerald-600 font-semibold tabular-nums">{row.accepted}</td>
                    <td className="px-5 py-3.5 text-right text-red-600 font-semibold tabular-nums">{row.rejected}</td>
                    <td className="px-5 py-3.5 text-right text-slate-500 tabular-nums">{row.pending}</td>
                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                          <div className="h-full rounded-full bg-brand-500" style={{ width: `${rate}%` }} />
                        </div>
                        <span className="text-xs font-semibold text-slate-600 tabular-nums w-8 text-right">{rate}%</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
