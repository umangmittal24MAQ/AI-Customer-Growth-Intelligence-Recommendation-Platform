import { TrendingUp, TrendingDown, Minus, Users, Zap, Activity, Clock, DollarSign, Info } from 'lucide-react'

const COLOR_MAP = {
  emerald: { bar: 'bg-emerald-500', text: 'text-emerald-600', bg: 'bg-emerald-50' },
  blue:    { bar: 'bg-blue-500',    text: 'text-blue-600',    bg: 'bg-blue-50'    },
  amber:   { bar: 'bg-amber-500',   text: 'text-amber-600',   bg: 'bg-amber-50'   },
  red:     { bar: 'bg-red-500',     text: 'text-red-600',     bg: 'bg-red-50'     },
}

function SubBar({ icon: Icon, label, pct, rawLabel, color = 'blue' }) {
  const c = COLOR_MAP[color] || COLOR_MAP.blue
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500">
          <Icon size={13} className={c.text} />
          {label}
        </span>
        <span className="text-[11px] font-bold text-gray-700 tabular-nums">{rawLabel}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${c.bar}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  )
}

export default function BandwidthPanel({ bwData, compact = false }) {
  if (!bwData) return null

  const { overall, trendLabel, direction, trendDataSimulated, timeToCapacity, headroomLabel, headroomDollars, dimensions } = bwData

  const overallColor = overall >= 70 ? 'emerald' : overall >= 40 ? 'blue' : 'amber'
  const oc = COLOR_MAP[overallColor]

  const TrendIcon = direction === 'up' ? TrendingUp : direction === 'down' ? TrendingDown : Minus
  const trendColor = direction === 'up' ? 'text-emerald-600' : direction === 'down' ? 'text-red-500' : 'text-gray-400'

  if (compact) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className={`text-xl font-black tabular-nums ${oc.text}`}>{overall}%</span>
          <span className={`flex items-center gap-1 text-[11px] font-semibold ${trendColor}`}>
            <TrendIcon size={13} />
            {trendLabel}
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full rounded-full ${oc.bar} transition-all duration-700`} style={{ width: `${overall}%` }} />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Overall */}
      <div className="space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <span className={`text-3xl font-black tabular-nums ${oc.text}`}>{overall}%</span>
            <span className={`flex items-center gap-1 text-[12px] font-semibold ${trendColor}`}>
              <TrendIcon size={14} />
              {trendLabel}
            </span>
          </div>
          {trendDataSimulated && (
            <span className="flex items-center gap-1 text-[10px] text-gray-400 bg-gray-50 border border-gray-200/60 px-2 py-0.5 rounded-full">
              <Info size={10} />
              trend simulated
            </span>
          )}
        </div>
        <div className="h-2.5 w-full rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full rounded-full ${oc.bar} transition-all duration-700`} style={{ width: `${overall}%` }} />
        </div>
      </div>

      {/* Sub-bars */}
      <div className="space-y-3 pt-1 border-t border-gray-100">
        <SubBar
          icon={Users}
          label="Seats"
          pct={dimensions.seats.pct}
          rawLabel={dimensions.seats.label}
          color={dimensions.seats.color}
        />
        <SubBar
          icon={Zap}
          label="Feature Adoption"
          pct={dimensions.adoption.pct}
          rawLabel={dimensions.adoption.label}
          color={dimensions.adoption.color}
        />
        <SubBar
          icon={Activity}
          label="Usage Frequency"
          pct={dimensions.frequency.pct}
          rawLabel={dimensions.frequency.label}
          color={dimensions.frequency.color}
        />
      </div>

      {/* Footer: headroom + time to capacity */}
      <div className="space-y-1.5 pt-3 border-t border-gray-100">
        {headroomDollars > 0 && (
          <div className="flex items-center gap-2 text-[12px] text-gray-600">
            <DollarSign size={13} className="text-blue-500 shrink-0" />
            <span>{headroomLabel}</span>
          </div>
        )}
        {timeToCapacity && (
          <div className="flex items-center gap-2 text-[12px] text-gray-600">
            <Clock size={13} className="text-violet-500 shrink-0" />
            <span>{timeToCapacity}</span>
            {trendDataSimulated && <span className="text-[10px] text-gray-400">(projected)</span>}
          </div>
        )}
      </div>
    </div>
  )
}
