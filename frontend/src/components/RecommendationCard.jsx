import { submitFeedback } from '../api/client'

const TYPE_STYLES = {
  retention: 'bg-red-50 text-red-700',
  discount: 'bg-red-50 text-red-700',
  escalation: 'bg-orange-50 text-orange-700',
  feature_adoption: 'bg-amber-50 text-amber-700',
  cross_sell: 'bg-blue-50 text-blue-700',
  upsell: 'bg-indigo-50 text-indigo-700',
}

export default function RecommendationCard({ rec, onUpdated }) {
  const handle = async (status) => {
    await submitFeedback(rec.id, status)
    onUpdated?.()
  }

  const statusBadge = {
    accepted: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    pending: 'bg-slate-100 text-slate-500',
  }[rec.status || 'pending']

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-xs font-semibold px-2 py-0.5 rounded ${
                TYPE_STYLES[rec.type] || 'bg-slate-100 text-slate-600'
              }`}
            >
              {rec.type.replace('_', ' ')}
            </span>
            {rec.escalation_flag ? (
              <span className="text-xs font-semibold px-2 py-0.5 rounded bg-orange-100 text-orange-700">
                CSM escalation
              </span>
            ) : null}
            <span className={`text-xs font-semibold px-2 py-0.5 rounded ${statusBadge}`}>
              {rec.status || 'pending'}
            </span>
          </div>
          <h4 className="mt-2 font-semibold text-slate-900">{rec.title}</h4>
          <p className="mt-1 text-sm text-slate-600">{rec.justification}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-lg font-bold text-slate-900">
            ${Math.round(rec.revenue_opportunity).toLocaleString()}
          </div>
          <div className="text-xs text-slate-500">
            {Math.round(rec.confidence * 100)}% confidence
          </div>
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => handle('accepted')}
          disabled={rec.status === 'accepted'}
          className="px-3 py-1.5 text-sm font-medium rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-40"
        >
          Accept
        </button>
        <button
          onClick={() => handle('rejected')}
          disabled={rec.status === 'rejected'}
          className="px-3 py-1.5 text-sm font-medium rounded-md bg-slate-200 text-slate-700 hover:bg-slate-300 disabled:opacity-40"
        >
          Reject
        </button>
      </div>
    </div>
  )
}
