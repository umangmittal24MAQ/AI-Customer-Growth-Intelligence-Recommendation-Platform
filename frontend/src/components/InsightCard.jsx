import { AlertTriangle, TrendingUp, Activity, Sparkles } from 'lucide-react'

/*
 * Stage 6 of the schema-free pipeline (schema_free_pipeline_design.md §6).
 *
 * Generic renderer for one item of the backend's `insights` list (see
 * app/insight_llm.py + app/models.py's Insight contract:
 * {id, category, title, summary, metrics, chart_hint}).
 *
 * Insights are now produced by a single LLM reasoning pass over each
 * customer's actual data, in plain language, with no confidence score --
 * there's nothing here for a non-technical reader to do with a "62%
 * confidence" bar, so it's gone. `category` is free text chosen by the
 * model per-insight rather than a fixed enum; anything this component
 * doesn't recognize just falls back to a neutral style below, so a
 * brand-new category the backend starts emitting tomorrow still renders
 * correctly with zero changes here.
 */

// category -> red/green/violet/blue; falls back to the neutral "custom"
// style for any category the model chooses that isn't one of these.
const CATEGORY_STYLE = {
  risk: { icon: AlertTriangle, iconColor: 'text-red-500', badge: 'bg-red-100 text-red-700' },
  revenue: { icon: TrendingUp, iconColor: 'text-emerald-600', badge: 'bg-emerald-100 text-emerald-700' },
  usage: { icon: Activity, iconColor: 'text-violet-600', badge: 'bg-violet-100 text-violet-700' },
  custom: { icon: Sparkles, iconColor: 'text-blue-600', badge: 'bg-blue-100 text-blue-700' },
}

function styleFor(category) {
  return CATEGORY_STYLE[category] || CATEGORY_STYLE.custom
}

function formatMetricValue(value, unit) {
  if (value === null || value === undefined) return '—'
  const formatted = typeof value === 'number' ? value.toLocaleString() : String(value)
  return unit ? `${formatted} ${unit}` : formatted
}

export default function InsightCard({ insight }) {
  const style = styleFor(insight.category)
  const Icon = style.icon

  return (
    <div className="rounded-2xl border border-gray-100 p-4 transition-all hover:border-gray-200 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={16} className={style.iconColor} />
          <h4 className="text-[13px] font-bold text-gray-900 truncate">{insight.title}</h4>
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full uppercase shrink-0 ${style.badge}`}>{insight.category}</span>
        </div>
      </div>

      <p className="text-[13px] leading-relaxed mb-3 text-gray-700">{insight.summary}</p>

      {insight.metrics?.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
          {insight.metrics.map((m, i) => (
            <div key={i}>
              <p className="text-[9px] font-bold uppercase tracking-widest text-gray-400">{m.label}</p>
              <p className="text-[13px] font-semibold text-gray-800 mt-0.5">{formatMetricValue(m.value, m.unit)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
