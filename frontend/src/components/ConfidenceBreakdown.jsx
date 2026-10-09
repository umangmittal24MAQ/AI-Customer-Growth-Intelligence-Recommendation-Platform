import { motion } from 'framer-motion'

const LABELS = {
  llm_confidence: 'Agent Self-Assessment',
  data_completeness: 'Data Completeness',
  retrieval_fit: 'Catalog Match',
  fallback_penalty: 'Fallback Penalty',
}

function Bar({ label, value, delay = 0 }) {
  const pct = Math.round(Math.min(Math.max((value || 0), 0), 1) * 100)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-400'
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11px] font-medium text-gray-500 w-36 shrink-0 text-right">{label}</span>
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }}
          transition={{ delay, duration: 0.5, ease: 'easeOut' }}
          className={`h-full rounded-full ${color}`} />
      </div>
      <span className="text-[11px] font-bold text-gray-700 w-8 tabular-nums">{pct}%</span>
    </div>
  )
}

export default function ConfidenceBreakdown({ confidence, breakdown }) {
  if (!confidence && !breakdown) return null
  return (
    <div className="space-y-2.5 py-2">
      <Bar label="Overall Score" value={typeof confidence === 'number' ? confidence : 0} delay={0} />
      {breakdown && Object.entries(breakdown).map(([key, val], i) => (
        <Bar key={key} label={LABELS[key] || key} value={val} delay={(i + 1) * 0.06} />
      ))}
    </div>
  )
}
