import { useEffect, useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { getCustomers, getCustomerAnalysis } from '../api/client'
import { BarChart3, Activity, DollarSign, Gauge } from 'lucide-react'
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

import BandwidthPanel from '../components/BandwidthPanel'

function Card({ children, className = '' }) {
  return <div className={`bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden ${className}`}>{children}</div>
}

function parseMoney(val) {
  if (typeof val === 'number') return val;
  if (typeof val === 'string') return Number(val.replace(/[^0-9.-]+/g,"")) || 0;
  return 0;
}

export default function Tracking() {
  const [customers, setCustomers] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [loadingCustomers, setLoadingCustomers] = useState(true)
  const [loadingAnalysis, setLoadingAnalysis] = useState(false)
  
  useEffect(() => {
    getCustomers().then(setCustomers).finally(() => setLoadingCustomers(false))
  }, [])

  useEffect(() => {
    if (!selectedId) {
      setAnalysis(null)
      return
    }
    setLoadingAnalysis(true)
    getCustomerAnalysis(selectedId).then(setAnalysis).finally(() => setLoadingAnalysis(false))
  }, [selectedId])

  const factorData = useMemo(() => {
    if (!analysis?.churn_analysis?.factor_breakdown) return []
    return Object.entries(analysis.churn_analysis.factor_breakdown).map(([k, v]) => ({ name: k, value: v }))
  }, [analysis])

  const bwData = useMemo(() => {
    if (!analysis) return null
    return analysis.bandwidth_data
  }, [analysis])

  const bandwidth = bwData?.overall || analysis?.bandwidth_utilization_pct || 0

  const usageData = useMemo(() => {
    if (analysis?.usage_history && Array.isArray(analysis.usage_history)) return analysis.usage_history
    
    if (bwData) {
      const { overall, previous } = bwData;
      const today = new Date();
      const m1 = new Date(today.getFullYear(), today.getMonth() - 2).toLocaleString('default', { month: 'short' });
      const m2 = new Date(today.getFullYear(), today.getMonth() - 1).toLocaleString('default', { month: 'short' });
      const m3 = today.toLocaleString('default', { month: 'short' });
      const diff = overall - previous;
      const month2 = Math.round(previous + diff / 2);

      return [
        { name: m1, value: previous },
        { name: m2, value: month2 },
        { name: m3, value: overall }
      ]
    }

    return [
      { name: 'Current', value: 100 }
    ]
  }, [analysis, bwData])

  const revData = useMemo(() => {
    if (!analysis) return []
    const current = parseMoney(analysis.customer_summary?.mrr) || 0
    const opp = parseMoney(analysis.executive_summary?.estimated_revenue_opportunity) || parseMoney(analysis.business_impact?.additional_revenue) || 0
    return [
      { name: 'Current Spend (MRR)', value: current },
      { name: 'Opportunity', value: opp }
    ]
  }, [analysis])

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div>
        <h1 className="text-[22px] font-extrabold text-gray-900 tracking-tight">Analytics</h1>
        <p className="text-[13px] text-gray-500 mt-0.5">Individual customer insights and telemetry</p>
      </div>

      <Card className="p-5">
        <label className="text-[13px] font-bold text-gray-700 mb-2 block">Select Customer</label>
        <select 
          className="w-full md:w-1/3 px-3 py-2 rounded-xl border border-gray-200 text-[13px] font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          value={selectedId || ''}
          onChange={e => setSelectedId(e.target.value)}
          disabled={loadingCustomers}
        >
          <option value="">-- Choose a customer --</option>
          {customers.map(c => <option key={c.customer_id} value={c.customer_id}>{c.company_name}</option>)}
        </select>
      </Card>

      {!selectedId && !loadingAnalysis && (
        <Card className="p-16 flex flex-col items-center justify-center text-center">
           <BarChart3 size={40} className="text-gray-300 mb-3" />
           <p className="text-[14px] font-semibold text-gray-500">Select a customer to view their analysis</p>
        </Card>
      )}

      {loadingAnalysis && (
        <div className="space-y-4 animate-pulse">
           <div className="grid grid-cols-2 gap-4">
             <div className="h-64 skeleton" />
             <div className="h-64 skeleton" />
             <div className="h-64 skeleton" />
             <div className="h-64 skeleton" />
           </div>
        </div>
      )}

      {analysis && !loadingAnalysis && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fade-in">
          {/* Churn Score Breakdown */}
          <Card>
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
              <BarChart3 size={16} className="text-blue-600" />
              <h3 className="text-[14px] font-bold text-gray-900">Churn Score Breakdown</h3>
            </div>
            <div className="p-5">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={factorData} layout="vertical" margin={{ top: 0, right: 0, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e5e7eb', fontSize: 12 }} />
                  <Bar dataKey="value" fill="#6366f1" radius={[0, 4, 4, 0]} barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* Usage Trend */}
          <Card>
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
              <Activity size={16} className="text-emerald-600" />
              <h3 className="text-[14px] font-bold text-gray-900">Usage Trend</h3>
            </div>
            <div className="p-5">
              {usageData.length > 1 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={usageData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e5e7eb', fontSize: 12 }} />
                    <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={3} dot={{ r: 4, fill: '#10b981', strokeWidth: 0 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex flex-col items-center justify-center h-[240px] text-center">
                  <p className="text-[13px] font-semibold text-gray-700">Current Usage</p>
                  <p className="text-[11px] text-gray-500 mt-1">{analysis.customer_insights?.usage_trend || 'No historical data available.'}</p>
                </div>
              )}
            </div>
          </Card>

          {/* Revenue Opportunity vs Spend */}
          <Card>
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
              <DollarSign size={16} className="text-amber-500" />
              <h3 className="text-[14px] font-bold text-gray-900">Spend vs. Opportunity</h3>
            </div>
            <div className="p-5">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={revData} margin={{ top: 10, right: 0, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickFormatter={v => `$${v}`} axisLine={false} tickLine={false} />
                  <Tooltip formatter={v => `$${v.toLocaleString()}`} contentStyle={{ borderRadius: 12, border: '1px solid #e5e7eb', fontSize: 12 }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={40}>
                    {revData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={index === 0 ? '#94a3b8' : '#f59e0b'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* Capacity & Usage Analysis */}
          <Card>
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
              <Gauge size={16} className="text-violet-600" />
              <h3 className="text-[14px] font-bold text-gray-900">Capacity &amp; Usage Analysis</h3>
            </div>
            <div className="p-5">
              {bwData
                ? <BandwidthPanel bwData={bwData} />
                : <p className="text-[13px] text-gray-400 text-center py-8">No usage data available for this customer.</p>
              }
            </div>
          </Card>
        </div>
      )}
    </motion.div>
  )
}
