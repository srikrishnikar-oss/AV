export const API_BASE = ''
export const DEFAULT_DATASET = 'full'
export const DEFAULT_SOURCE = 'Cubbon Park, Bengaluru'
export const DEFAULT_DESTINATION = 'Indiranagar Metro Station, Bengaluru'
export const DEFAULT_PROVIDER = 'Jio'
export const DEFAULT_CONNECTIVITY_BIAS = 0.72

export const ROUTE_STYLES = {
  Safe: { color: '#3fb950', halo: '#203126', weight: 5.2, dash: null, blocked: false },
  Balanced: { color: '#d29922', halo: '#342a17', weight: 4.6, dash: [10, 6], blocked: false },
  Fastest: { color: '#f85149', halo: '#351c1a', weight: 4.2, dash: [12, 8], blocked: true },
  Emergency: { color: '#58a6ff', halo: '#18283c', weight: 5, dash: [4, 6], blocked: false },
}

export const PAGE_DEFS = [
  { id: 'planner', label: 'Route Planner' },
  { id: 'dashboard', label: 'Comparison' },
  { id: 'adaptive-map', label: 'Signal Map' },
  { id: 'simulation', label: 'Simulation' },
]

export const ABOUT_FORMULA = 'signal_strength = Pt - 10 * n * log10(distance) - X'

export function roundValue(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '--'
  return Number(value).toFixed(digits)
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

export function normalizeValue(value, min, max) {
  if (max <= min) return 0
  return (value - min) / (max - min)
}

export function shortPlaceName(label) {
  return (label ?? '').split(',')[0]?.trim() || label || 'Unknown'
}

export function getRouteStyle(routeLabel, index = 0) {
  return ROUTE_STYLES[routeLabel] ?? {
    color: ['#3fb950', '#d29922', '#f85149', '#58a6ff'][index % 4],
    halo: '#1f242b',
    weight: 4.5,
    dash: null,
    blocked: false,
  }
}

export function computeRouteMetrics(route) {
  const distanceKm = route.segments.reduce((sum, segment) => sum + Number(segment.length_m || 0), 0) / 1000
  const weakSegments = route.segments.filter(
    (segment) => Number(segment.dead_zone_flag) === 1 || Number(segment.min_signal) < 45 || Number(segment.safe_flag) === 0,
  ).length
  const telemetryPenalty =
    route.segments.reduce((sum, segment) => sum + Number(segment.handover_risk || 0), 0) / Math.max(route.segments.length, 1)

  const signalLow = clamp(Math.round(route.min_signal - 6), 0, 100)
  const signalHigh = clamp(Math.round(route.avg_signal + 8), signalLow, 100)
  const confidenceLow = Math.max(signalLow, clamp(Math.round(route.avg_signal - 4), 0, 100))
  const confidenceHigh = clamp(Math.round(route.avg_signal + 11), confidenceLow, 100)
  const qualityScore = clamp(
    Math.round(route.avg_signal * 0.48 + route.estimated_bandwidth_mbps * 0.24 - route.risk_score * 42 - telemetryPenalty * 18),
    0,
    100,
  )

  return {
    distanceKm,
    weakSegments,
    telemetryPenalty,
    signalLow,
    signalHigh,
    confidenceLow,
    confidenceHigh,
    qualityScore,
    connectivityScore: clamp(Math.round(route.avg_signal), 0, 100),
    minScore: clamp(Math.round(route.min_signal), 0, 100),
    dBm: Math.round(-110 + (route.avg_signal / 100) * 55),
  }
}

export function getAutonomyProfile(route) {
  const summary = route.degradation_summary
  if (summary) {
    const order = ['FULL_AUTONOMY', 'REDUCED_SPEED', 'SUPERVISED_MODE', 'PULL_OVER']
    const labels = ['full autonomy', 'reduced speed', 'supervised', 'pull over']
    const values = order.map((state) => Number(summary[state] || 0))
    const total = values.reduce((sum, value) => sum + value, 0) || 1
    const dominantIndex = values.indexOf(Math.max(...values))
    return {
      level: labels[dominantIndex].replace(/\b\w/g, (char) => char.toUpperCase()),
      bars: dominantIndex >= 3 ? 1 : dominantIndex >= 2 ? 3 : 4,
      segments: values.map((value) => value / total),
      labels,
    }
  }

  const metrics = computeRouteMetrics(route)
  return {
    level: 'Full autonomy',
    bars: 4,
    segments: [0.58, 0.24, 0.12, 0.06],
    labels: ['full autonomy', 'reduced speed', 'supervised', 'pull over'],
  }
}

function isStrictSafeRoute(route) {
  if (typeof route.strict_safe === 'boolean') return route.strict_safe
  const summary = route.degradation_summary ?? {}
  return (
    Number(route.dead_zone_count || 0) === 0 &&
    !route.point_of_no_return &&
    !route.threshold_breach &&
    Number(summary.PULL_OVER || 0) === 0 &&
    Number(summary.SUPERVISED_MODE || 0) === 0
  )
}

function routeSafetyTuple(route) {
  const summary = route.degradation_summary ?? {}
  return [
    Number(route.dead_zone_count || 0),
    route.point_of_no_return ? 1 : 0,
    route.threshold_breach ? 1 : 0,
    Number(summary.PULL_OVER || 0),
    Number(summary.SUPERVISED_MODE || 0),
    Number(route.risk_score || 0),
    -Number(route.min_signal || 0),
    Number(route.travel_time_min || 0),
  ]
}

function routeEmergencyTuple(route) {
  const summary = route.degradation_summary ?? {}
  return [
    Number(route.dead_zone_count || 0),
    route.point_of_no_return ? 1 : 0,
    Number(summary.PULL_OVER || 0),
    Number(summary.SUPERVISED_MODE || 0),
    route.threshold_breach ? 1 : 0,
    Number(route.risk_score || 0),
    -Number(route.min_signal || 0),
    Number(route.travel_time_min || 0),
  ]
}

function routeBalancedTuple(route) {
  return [
    Number(route.dead_zone_count || 0),
    Number(route.risk_score || 0),
    -Number(route.min_signal || 0),
    Number(route.travel_time_min || 0),
  ]
}

function compareTuple(left, right) {
  const maxLength = Math.max(left.length, right.length)
  for (let index = 0; index < maxLength; index += 1) {
    const delta = Number(left[index] || 0) - Number(right[index] || 0)
    if (delta !== 0) return delta
  }
  return 0
}

export function normalizeRouteRoles(routes) {
  if (!routes.length) return []

  const canonicalLabels = ['Fastest', 'Balanced', 'Safe', 'Emergency']
  const hasCanonicalRoleSet = canonicalLabels.every((label) => routes.some((route) => route.route_label === label))
  if (hasCanonicalRoleSet) {
    return canonicalLabels
      .map((label) => routes.find((route) => route.route_label === label))
      .filter(Boolean)
      .map((route) => ({
        ...route,
        route_origin_label: route.route_origin_label ?? route.route_label,
        strict_safe: isStrictSafeRoute(route),
      }))
  }

  const remaining = routes.map((route) => ({
    ...route,
    route_origin_label: route.route_origin_label ?? route.route_label,
    strict_safe: isStrictSafeRoute(route),
  }))

  const assigned = new Map()

  function takeBest(label, tupleFn) {
    if (!remaining.length) return
    let bestIndex = 0
    for (let index = 1; index < remaining.length; index += 1) {
      if (compareTuple(tupleFn(remaining[index]), tupleFn(remaining[bestIndex])) < 0) {
        bestIndex = index
      }
    }
    const [best] = remaining.splice(bestIndex, 1)
    assigned.set(label, {
      ...best,
      route_label: label,
      route_role_label: label,
      strict_safe: label === 'Safe' ? isStrictSafeRoute(best) : best.strict_safe,
    })
  }

  takeBest('Safe', routeSafetyTuple)
  takeBest('Emergency', routeEmergencyTuple)
  takeBest('Fastest', (route) => [Number(route.travel_time_min || 0), Number(route.risk_score || 0)])
  takeBest('Balanced', routeBalancedTuple)

  return ['Fastest', 'Balanced', 'Safe', 'Emergency']
    .map((label) => assigned.get(label))
    .filter(Boolean)
}

export function scoreRoutesForAlpha(routes, alpha, options = {}) {
  if (!routes.length) return []
  const { applicationType = 'Navigation', providerBaseline = 'All providers', minSignalThresholdDbm = -92 } = options

  const resolveProviderSupport = (route) => {
    if (providerBaseline === 'All providers') {
      return {
        score: Number(route.operator_support_score ?? 1),
        bandwidth: Number(route.operator_support_bandwidth_mbps ?? route.estimated_bandwidth_mbps ?? 0),
      }
    }

    const supportByProvider = route.operator_support_by_provider?.[providerBaseline]
    return {
      score: Number(supportByProvider?.score ?? route.operator_support_score ?? 1),
      bandwidth: Number(supportByProvider?.bandwidth_mbps ?? route.operator_support_bandwidth_mbps ?? route.estimated_bandwidth_mbps ?? 0),
    }
  }

  const travelTimes = routes.map((route) => Number(route.travel_time_min || 0))
  const riskScores = routes.map((route) => Number(route.risk_score || 0))
  const minSignals = routes.map((route) => Number(route.min_signal || 0))
  const avgSignals = routes.map((route) => Number(route.avg_signal || 0))
  const bandwidths = routes.map((route) => resolveProviderSupport(route).bandwidth || Number(route.estimated_bandwidth_mbps || 0))
  const deadZones = routes.map((route) => Number(route.dead_zone_count || 0))
  const operatorSupport = routes.map((route) => resolveProviderSupport(route).score)

  const applicationProfiles = {
    Navigation: { travel: 0.4, risk: 0.22, signal: 0.23, bandwidth: 0.15 },
    Telematics: { travel: 0.16, risk: 0.3, signal: 0.28, bandwidth: 0.26 },
    'Ride-hail': { travel: 0.62, risk: 0.14, signal: 0.14, bandwidth: 0.1 },
    'OTA Update': { travel: 0.08, risk: 0.24, signal: 0.3, bandwidth: 0.38 },
  }
  const applicationRouteBias = {
    Navigation: { Balanced: -0.04, Safe: -0.01, Fastest: 0.03, Emergency: 0.08 },
    Telematics: { Balanced: -0.03, Safe: -0.02, Fastest: 0.08, Emergency: 0.03 },
    'Ride-hail': { Fastest: -0.05, Balanced: -0.01, Safe: 0.04, Emergency: 0.09 },
    'OTA Update': { Safe: -0.05, Emergency: -0.02, Balanced: 0.02, Fastest: 0.12 },
  }
  const profile = applicationProfiles[applicationType] ?? applicationProfiles.Navigation

  const travelMin = Math.min(...travelTimes)
  const travelMax = Math.max(...travelTimes)
  const riskMin = Math.min(...riskScores)
  const riskMax = Math.max(...riskScores)
  const minSignalMin = Math.min(...minSignals)
  const minSignalMax = Math.max(...minSignals)
  const avgSignalMin = Math.min(...avgSignals)
  const avgSignalMax = Math.max(...avgSignals)
  const bandwidthMin = Math.min(...bandwidths)
  const bandwidthMax = Math.max(...bandwidths)
  const deadZoneMax = Math.max(...deadZones, 1)
  const operatorSupportMin = Math.min(...operatorSupport)
  const operatorSupportMax = Math.max(...operatorSupport)

  return routes
    .map((route) => {
      const providerSupportMetrics = resolveProviderSupport(route)
      const travelPenalty = normalizeValue(Number(route.travel_time_min || 0), travelMin, travelMax)
      const riskPenalty = normalizeValue(Number(route.risk_score || 0), riskMin, riskMax)
      const deadZonePenalty = Number(route.dead_zone_count || 0) / deadZoneMax
      const signalPenalty = 1 - normalizeValue(Number(route.min_signal || 0), minSignalMin, minSignalMax)
      const continuityPenalty = 1 - normalizeValue(Number(route.avg_signal || 0), avgSignalMin, avgSignalMax)
      const bandwidthPenalty = 1 - normalizeValue(Number(providerSupportMetrics.bandwidth || route.estimated_bandwidth_mbps || 0), bandwidthMin, bandwidthMax)
      const providerPenalty =
        providerBaseline === 'All providers'
          ? 0
          : 1 - normalizeValue(Number(providerSupportMetrics.score ?? 1), operatorSupportMin, operatorSupportMax)
      const thresholdPenalty = route.threshold_breach ? 0.45 : 0
      const unsafePenalty = route.safe_flag ? 0 : 0.28
      const routeBias = applicationRouteBias[applicationType]?.[route.route_label] ?? 0

      const connectivityPenalty =
        riskPenalty * profile.risk +
        deadZonePenalty * 0.22 +
        signalPenalty * profile.signal +
        continuityPenalty * 0.1 +
        bandwidthPenalty * profile.bandwidth +
        providerPenalty * 0.34 +
        unsafePenalty +
        thresholdPenalty +
        routeBias

      const alphaScore = (1 - alpha) * (travelPenalty * (0.55 + profile.travel)) + alpha * connectivityPenalty
      return {
        ...route,
        operator_support_score_active: providerSupportMetrics.score,
        operator_support_bandwidth_mbps_active: providerSupportMetrics.bandwidth,
        alpha_score: alphaScore,
      }
    })
    .sort((left, right) => left.alpha_score - right.alpha_score)
}

export function getWinnerRoute(routes, alpha, options = {}) {
  return scoreRoutesForAlpha(routes, alpha, options)[0] ?? null
}

export function getModeLabel(routeLabel) {
  if (routeLabel === 'Emergency') return 'safety-critical mode'
  if (routeLabel === 'Safe') return 'connectivity-safe mode'
  if (routeLabel === 'Balanced') return 'balanced mode'
  return 'fastest mode'
}

export function buildSimulationState(route, progress) {
  if (!route?.path_geometry?.length) return null

  const index = Math.min(route.path_geometry.length - 1, Math.floor(progress * (route.path_geometry.length - 1)))
  const point = route.path_geometry[index]
  const metrics = computeRouteMetrics(route)
  const autonomy = getAutonomyProfile(route)

  return {
    point,
    progress,
    signal: clamp(Math.round(route.avg_signal - progress * 18), 0, 100),
    latencyRisk: clamp(Number(route.risk_score) + progress * 0.18, 0, 1),
    bandwidth: clamp(Math.round(route.estimated_bandwidth_mbps - progress * 12), 1, 120),
    autonomyLevel: autonomy.level,
    etaRemainingMin: Math.max(0.2, Number(route.travel_time_min || 0) * (1 - progress)),
    confidence: `${metrics.confidenceLow}% - ${metrics.confidenceHigh}%`,
  }
}

export function getOfflineFallbackSuggestions(route, prediction = null, applicationType = 'Navigation') {
  if (!route) return []

  const severity = prediction?.next_risk?.severity ?? 'clear'
  const hasPoorSignal =
    Number(route.dead_zone_count || 0) > 0 ||
    Number(route.min_signal || 0) < 45 ||
    Number(route.risk_score || 0) >= 0.32 ||
    severity === 'warning' ||
    severity === 'critical'

  if (!hasPoorSignal) return []

  const suggestions = [
    'Download offline maps for the full corridor before departure.',
    'Switch to SMS-based navigation or text-only guidance if mobile data drops.',
  ]

  if (applicationType === 'OTA Update' || applicationType === 'Telematics') {
    suggestions.push('Pause non-critical cloud sync and queue uploads until the signal recovers.')
  }

  if (severity === 'critical' || Number(route.dead_zone_count || 0) > 0) {
    suggestions.push('Cache the remaining route locally before entering the weak-signal stretch.')
  }

  return suggestions
}
