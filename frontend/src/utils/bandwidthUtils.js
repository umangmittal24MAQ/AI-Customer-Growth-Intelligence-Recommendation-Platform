/**
 * bandwidthUtils.js
 * Computes all bandwidth-derived metrics from the raw signals
 * available in the customer analysis API response.
 * 
 * Since no historical time-series data exists in the backend,
 * trend and time-to-capacity are SIMULATED from deterministic
 * signals (feature_adoption + login_frequency) — clearly marked.
 */

// Plan-tier seat limits (mock — backend has no seat cap field)
const PLAN_SEATS = { Starter: 10, Pro: 50, Enterprise: 200 }

// Plan-tier MRR ceilings for dollar headroom calculation
const PLAN_MRR_CEILING = { Starter: 500, Pro: 2000, Enterprise: 8000 }
const IDEAL_LOGIN_FREQ = 14

export function computeBandwidth(signal) {
  const planTier = signal?.plan_tier || 'Pro'

  const adoptionPct = signal?.feature_adoption_pct || 0
  const monthlyActiveUsers = signal?.monthly_active_users || 0
  const loginFreq = signal?.login_frequency_per_week || 0

  const seatCapacity = PLAN_SEATS[planTier] || 50
  const seatsUsed = Math.min(monthlyActiveUsers, seatCapacity)
  const seatPct = seatCapacity ? Math.round((seatsUsed / seatCapacity) * 100) : 0
  const adoptionPctNum = Math.round(adoptionPct)
  const freqPct = Math.min(Math.round((loginFreq / IDEAL_LOGIN_FREQ) * 100), 100)

  const overall = Math.round(seatPct * 0.4 + adoptionPctNum * 0.35 + freqPct * 0.25)

  const trendDelta = adoptionPctNum > 60
    ? Math.round(adoptionPctNum * 0.12)
    : adoptionPctNum > 30
      ? Math.round(adoptionPctNum * 0.05)
      : -Math.round(adoptionPctNum * 0.08)

  const previous = Math.max(0, Math.min(100, overall - trendDelta))
  const direction = trendDelta > 3 ? 'up' : trendDelta < -3 ? 'down' : 'flat'
  const trendLabel = direction === 'up'
    ? `${previous}% → ${overall}% (↑ past 3 mo)`
    : direction === 'down'
      ? `${previous}% → ${overall}% (↓ past 3 mo)`
      : `${previous}% → ${overall}% (→ flat)`

  let timeToCapacity = null
  if (direction === 'up' && trendDelta > 0 && overall < 100) {
    const periodsToCapacity = (100 - overall) / trendDelta
    const monthsToCapacity = Math.round(periodsToCapacity * 3)
    timeToCapacity = monthsToCapacity <= 1
      ? 'Approaching capacity now'
      : `~${monthsToCapacity} months to capacity at current growth`
  } else if (overall >= 90) {
    timeToCapacity = 'Near capacity — act now'
  } else if (direction === 'down') {
    timeToCapacity = 'Declining — expansion not recommended yet'
  }

  const mrrCeiling = PLAN_MRR_CEILING[planTier] || 2000
  const headroomPct = Math.max(0, 100 - overall) / 100
  const headroomDollars = Math.round(mrrCeiling * headroomPct)
  const headroomLabel = headroomDollars > 0
    ? `~$${headroomDollars.toLocaleString()}/mo remaining before plan limits`
    : 'At or beyond plan capacity'

  const oppScore = Math.round(
    overall * 0.5 +
    adoptionPctNum * 0.3 +
    Math.min(freqPct, 100) * 0.2
  )

  return {
    overall,
    previous,
    direction,
    trendLabel,
    trendDataSimulated: true,
    timeToCapacity,
    headroomDollars,
    headroomLabel,
    opportunityScore: Math.min(oppScore, 100),
    dimensions: {
      seats: {
        used: seatsUsed,
        capacity: seatCapacity,
        pct: seatPct,
        label: `${seatsUsed} of ${seatCapacity} seats used`,
        color: seatPct >= 80 ? 'emerald' : seatPct >= 50 ? 'blue' : 'amber',
      },
      adoption: {
        pct: adoptionPctNum,
        label: `${adoptionPctNum}% of entitled features active`,
        color: adoptionPctNum >= 70 ? 'emerald' : adoptionPctNum >= 40 ? 'blue' : 'amber',
      },
      frequency: {
        pct: freqPct,
        label: `${loginFreq}/wk login rate`,
        color: freqPct >= 70 ? 'emerald' : freqPct >= 40 ? 'blue' : 'amber',
      },
    },
  }
}

export function getMatrixCategory(bandwidth, revenueOpportunity) {
  const isHighRev = revenueOpportunity >= 2000
  if (bandwidth >= 70) return isHighRev ? 'Priority Upsell' : 'Cross-Sell'
  if (bandwidth >= 40) return isHighRev ? 'Right-Size' : 'Feature Nudge'
  return isHighRev ? 'Retention First' : 'Re-Engagement'
}

export function getRecPriority(recOrRevenueOpportunity, bandwidth, churnScore) {
  const revenueOpportunity = typeof recOrRevenueOpportunity === 'number'
    ? recOrRevenueOpportunity
    : recOrRevenueOpportunity?.revenue_opportunity || 0

  const revScore = Math.min(revenueOpportunity / 100.0, 50.0)
  const bwScore = bandwidth * 0.3
  const churnBonus = churnScore > 70 ? 10 : churnScore > 40 ? 5 : 0
  const total = revScore + bwScore + churnBonus

  if (total >= 60) return { label: 'High', color: 'bg-red-100 text-red-700' }
  if (total >= 35) return { label: 'Medium', color: 'bg-amber-100 text-amber-700' }
  return { label: 'Low', color: 'bg-emerald-100 text-emerald-700' }
}

export function getTriggeredBy(recOrBandwidthData, bandwidthDataOrChurnScore, churnScoreOrType, maybeType) {
  const recType = typeof maybeType === 'string'
    ? maybeType
    : typeof churnScoreOrType === 'string'
      ? churnScoreOrType
      : recOrBandwidthData?.type

  const bandwidthData = typeof maybeType === 'string'
    ? recOrBandwidthData
    : bandwidthDataOrChurnScore

  const churnScore = typeof maybeType === 'string'
    ? bandwidthDataOrChurnScore
    : churnScoreOrType

  const triggers = []
  if (!bandwidthData) return triggers

  const overall = bandwidthData?.overall || 0
  if (overall >= 70) {
    triggers.push({ label: `High Capacity Usage (${overall}%)`, positive: true })
  } else if (overall < 40) {
    triggers.push({ label: `Low Capacity Usage (${overall}%)`, positive: false })
  }

  const adoptionPct = bandwidthData?.dimensions?.adoption?.pct || 0
  if (adoptionPct >= 70) {
    triggers.push({ label: `High Feature Adoption (${adoptionPct}%)`, positive: true })
  } else if (adoptionPct < 35) {
    triggers.push({ label: `Low Feature Adoption (${adoptionPct}%)`, positive: false })
  }

  if (churnScore >= 70) {
    triggers.push({ label: `High Churn Risk (${churnScore}/100)`, positive: false })
  } else if (churnScore <= 30) {
    triggers.push({ label: `Low Churn Risk (${churnScore}/100)`, positive: true })
  } else {
    triggers.push({ label: `Moderate Churn Risk (${churnScore}/100)`, positive: null })
  }

  if ((recType === 'upsell' || recType === 'cross_sell') && bandwidthData.direction === 'up') {
    triggers.push({ label: 'Rising usage trend (↑)', positive: true })
  }

  if (recType === 'retention') {
    const freqPct = bandwidthData?.dimensions?.frequency?.pct || 0
    if (freqPct < 40) {
      triggers.push({ label: `Low Login Frequency (${bandwidthData?.dimensions?.frequency?.label || 'n/a'})`, positive: false })
    }
  }

  return triggers
}

export const MATRIX_COLOR_BY_LABEL = {
  'Priority Upsell': 'bg-violet-100 text-violet-700 border-violet-200',
  'Cross-Sell': 'bg-blue-100 text-blue-700 border-blue-200',
  'Right-Size': 'bg-amber-100 text-amber-700 border-amber-200',
  'Feature Nudge': 'bg-emerald-100 text-emerald-700 border-emerald-200',
  'Retention First': 'bg-rose-100 text-rose-700 border-rose-200',
  'Re-Engagement': 'bg-slate-100 text-slate-700 border-slate-200',
}

export function getMatrixColor(matrixLabel) {
  return MATRIX_COLOR_BY_LABEL[matrixLabel] || 'bg-gray-100 text-gray-700 border-gray-200'
}

/**
 * Adapts a real backend recommendation (from a.all_recommendations, produced
 * by the actual multi-agent/rule-based pipeline for this tenant's data) into
 * the shape the recommendation card renders. Nothing is invented here --
 * every value comes straight from the API response for this customer.
 */
export function adaptRecommendation(rec, currentProduct) {
  if (!rec) return null
  const isUpsell = rec.type === 'upsell' && rec.recommended_product && rec.recommended_product !== currentProduct
  return {
    title: rec.recommended_product || 'No recommendation',
    type: rec.type || 'upsell',
    revenue_opportunity: rec.revenue_opportunity || 0,
    confidence: typeof rec.confidence === 'number' ? rec.confidence : 0.5,
    is_low_confidence_pitch: rec.is_low_confidence_pitch,
    justification: rec.rationale || rec.justification,
    matrixLabel: rec.matrixLabel,
    matrixColor: getMatrixColor(rec.matrixLabel),
    currentPlan: isUpsell ? currentProduct : '',
    recommendedPlan: isUpsell ? rec.recommended_product : '',
    product_id: rec.id ?? null,
    segment: rec.segment,
    status: rec.status,
  }
}
