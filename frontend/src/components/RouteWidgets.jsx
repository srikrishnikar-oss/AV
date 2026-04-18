import { computeRouteMetrics, getAutonomyProfile, getRouteStyle, roundValue } from '../lib/routing'

function describeRoute(route) {
  const strictSafe = Boolean(route.strict_safe)
  const hasPnr = Boolean(route.point_of_no_return)
  const deadZones = Number(route.dead_zone_count || 0)
  const risk = Number(route.risk_score || 0)

  if (strictSafe) return 'No dead zones or forced fallback points detected on this corridor.'
  if (deadZones > 0) return `Crosses ${deadZones} dead-zone ${deadZones === 1 ? 'segment' : 'segments'} and needs fallback planning.`
  if (hasPnr) return 'Contains a point of no return before a weak-signal stretch.'
  if (risk >= 0.35) return 'Carries elevated connectivity risk even without a hard dead zone.'
  return 'Trades travel time and connectivity based on the current route conditions.'
}

function routeBadge(route) {
  if (route.strict_safe) return 'safe'
  if (Number(route.dead_zone_count || 0) > 0) return 'warning'
  if (route.point_of_no_return || route.threshold_breach) return 'caution'
  return 'stable'
}

export function DegradationStrip({ route }) {
  const profile = getAutonomyProfile(route)
  const colors = ['#3fb950', '#d29922', '#30363d', '#f85149']

  return (
    <div className="degradation-strip">
      {profile.segments.map((segment, index) => (
        <span
          key={`${route.route_label}-${index}`}
          className="degradation-strip__segment"
          style={{ flex: segment, background: colors[index] }}
          title={profile.labels[index]}
        />
      ))}
    </div>
  )
}

export function ConfidenceLine({ route }) {
  const metrics = computeRouteMetrics(route)
  return (
    <p className="confidence-line">
      connectivity: <span>{metrics.confidenceLow}% - {metrics.confidenceHigh}%</span>
    </p>
  )
}

export function SignalMeter({ route }) {
  const profile = getAutonomyProfile(route)
  const metrics = computeRouteMetrics(route)

  return (
    <div className="signal-meter">
      <div className="signal-meter__bars">
        {[0, 1, 2, 3, 4].map((index) => (
          <span
            key={index}
            className={`signal-meter__bar ${index < profile.bars ? 'signal-meter__bar--lit' : ''}`}
            style={{ height: `${10 + index * 7}px` }}
          />
        ))}
      </div>
      <div className="signal-meter__meta">
        <strong>{metrics.dBm} dBm</strong>
        <span>{profile.level}</span>
      </div>
    </div>
  )
}

export function RouteCard({ route, alpha, selected, onSelect, badgeLabel = null, blockedText = '' }) {
  const style = getRouteStyle(route.route_label)
  const metrics = computeRouteMetrics(route)
  const strictSafe = Boolean(route.strict_safe)
  const badge = badgeLabel ?? (route.route_label === 'Safe' && !strictSafe ? 'safest available' : routeBadge(route))
  const title =
    route.route_label === 'Safe'
      ? 'Safe route'
      : route.route_label === 'Balanced'
        ? 'Balanced route'
        : route.route_label === 'Fastest'
          ? 'Fastest route'
          : 'Emergency route'
  const summary = describeRoute(route)

  return (
    <button
      type="button"
      className={`route-card ${selected ? 'route-card--selected' : ''} ${alpha > 0.6 && route.route_label === 'Safe' ? 'route-card--boosted' : ''}`}
      style={{ '--route-card-color': style.color }}
      onClick={() => onSelect?.(route.route_label)}
    >
      <div className="route-card__top">
        <div>
          <h3>{title}</h3>
          <p>{summary}</p>
        </div>
        <span className={`route-card__badge route-card__badge--${badge.replace(/\s+/g, '-')}`}>{badge}</span>
      </div>

      {blockedText ? <div className="route-card__blocked">{blockedText}</div> : null}
      {route.route_label === 'Safe' && !strictSafe ? (
        <div className="route-card__blocked">
          No fully safe route is available. This is the lowest-risk corridor in the current graph.
        </div>
      ) : null}

      <div className="route-card__stats">
        <span>ETA {roundValue(route.travel_time_min, 1)} min</span>
        <span>{metrics.signalLow}-{metrics.signalHigh}%</span>
        <span>dead zones {route.dead_zone_count}</span>
      </div>

      <ConfidenceLine route={route} />
      <DegradationStrip route={route} />

      <div className="route-card__footer">
        <span>{roundValue(metrics.distanceKm, 1)} km</span>
        <span>{metrics.weakSegments} weak segments</span>
        <span>{roundValue(metrics.telemetryPenalty * 10, 1)} telemetry</span>
      </div>
    </button>
  )
}
