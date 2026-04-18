import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { loadGoogleMaps } from './googleMaps'

const API_BASE = 'http://127.0.0.1:8000'
const DEFAULT_SOURCE = 'Cubbon Park, Bengaluru'
const DEFAULT_DESTINATION = 'Indiranagar Metro Station, Bengaluru'
const DEFAULT_PROVIDER = 'Jio'
const DEFAULT_CONNECTIVITY_BIAS = 44
const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY

const ROUTE_STYLES = {
  Safe: { color: '#5ef2a9', halo: '#0a3f26', weight: 7.4 },
  Balanced: { color: '#b5ff92', halo: '#30511f', weight: 6.8 },
  Fastest: { color: '#60b8ff', halo: '#123956', weight: 6.2 },
  Emergency: { color: '#ff7079', halo: '#51151d', weight: 7.6 },
}

const ROUTE_META = {
  Fastest: {
    title: 'Fastest route',
    description: 'Skips stronger coverage pockets when the time savings are worth it.',
  },
  Balanced: {
    title: 'Balanced route',
    description: 'A practical middle ground between ETA pressure and network continuity.',
  },
  Safe: {
    title: 'Most connected route',
    description: 'Detours toward stronger coverage zones for better autonomy stability.',
  },
  Emergency: {
    title: 'Emergency route',
    description: 'Avoids risky corridors aggressively when safety rules dominate travel time.',
  },
}

const BUILD_ORDER = [
  "Keep `data/raw/road_segments.csv` anchored to Bengaluru roads so route geometry stays real.",
  "Use `data/raw/towers.csv` as the telecom baseline, then layer provider-specific coverage next.",
  "Inject `data/raw/feedback.csv` telemetry traces to turn static weak zones into adaptive penalties.",
  'Let signal, bandwidth, and telemetry penalties re-rank candidate routes in near real time.',
]

function roundValue(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '--'
  return Number(value).toFixed(digits)
}

function shortPlaceName(label) {
  return (label ?? '').split(',')[0]?.trim() || label || 'Unknown'
}

function getRouteStyle(routeLabel, index) {
  return ROUTE_STYLES[routeLabel] ?? {
    color: ['#60b8ff', '#b5ff92', '#5ef2a9', '#ff7079'][index % 4],
    halo: '#102635',
    weight: 6.5,
  }
}

function normalizeValue(value, min, max) {
  if (max <= min) return 0
  return (value - min) / (max - min)
}

function getWinnerLabel(routes, connectivityBias) {
  if (!routes.length) return ''

  const alpha = connectivityBias / 100
  const travelTimes = routes.map((route) => Number(route.travel_time_min || 0))
  const riskScores = routes.map((route) => Number(route.risk_score || 0))
  const minSignals = routes.map((route) => Number(route.min_signal || 0))
  const avgSignals = routes.map((route) => Number(route.avg_signal || 0))
  const bandwidths = routes.map((route) => Number(route.estimated_bandwidth_mbps || 0))
  const deadZones = routes.map((route) => Number(route.dead_zone_count || 0))

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

  const ranked = routes
    .map((route) => {
      const travelPenalty = normalizeValue(Number(route.travel_time_min || 0), travelMin, travelMax)
      const riskPenalty = normalizeValue(Number(route.risk_score || 0), riskMin, riskMax)
      const deadZonePenalty = Number(route.dead_zone_count || 0) / deadZoneMax
      const signalPenalty = 1 - normalizeValue(Number(route.min_signal || 0), minSignalMin, minSignalMax)
      const continuityPenalty = 1 - normalizeValue(Number(route.avg_signal || 0), avgSignalMin, avgSignalMax)
      const bandwidthPenalty = 1 - normalizeValue(Number(route.estimated_bandwidth_mbps || 0), bandwidthMin, bandwidthMax)
      const unsafePenalty = route.safe_flag ? 0 : 0.35

      const connectivityPenalty =
        riskPenalty * 0.34 +
        deadZonePenalty * 0.24 +
        signalPenalty * 0.18 +
        continuityPenalty * 0.12 +
        bandwidthPenalty * 0.12 +
        unsafePenalty

      const score = (1 - alpha) * travelPenalty + alpha * connectivityPenalty

      return { route, score }
    })
    .sort((left, right) => left.score - right.score)

  return ranked[0]?.route.route_label ?? routes[0]?.route_label ?? ''
}

function getRouteDisplay(route) {
  return ROUTE_META[route.route_label] ?? {
    title: `${route.route_label} route`,
    description: 'Route option derived from the live Bengaluru road and connectivity graph.',
  }
}

function computeRouteMetrics(route) {
  const distanceKm = route.segments.reduce((sum, segment) => sum + Number(segment.length_m || 0), 0) / 1000
  const weakSegments = route.segments.filter(
    (segment) => Number(segment.dead_zone_flag) === 1 || Number(segment.min_signal) < 45 || Number(segment.safe_flag) === 0,
  ).length
  const telemetryPenalty =
    route.segments.reduce((sum, segment) => sum + Number(segment.handover_risk || 0), 0) / Math.max(route.segments.length, 1)
  const qualityScore = Math.max(
    0,
    Math.min(
      100,
      Math.round(
        route.avg_signal * 0.52 +
          route.min_signal * 0.18 +
          route.estimated_bandwidth_mbps * 0.22 -
          route.risk_score * 42 -
          telemetryPenalty * 28,
      ),
    ),
  )

  return {
    distanceKm,
    weakSegments,
    telemetryPenalty,
    qualityScore,
    connectivityScore: Math.round(route.avg_signal),
    minScore: Math.round(route.min_signal),
  }
}

function getRouteBadge(route, index, winnerLabel) {
  if (route.route_label === winnerLabel) return 'Best'
  if (index === 1) return 'Runner-up'
  if (route.route_label === 'Emergency') return 'Shield'
  return 'Fallback'
}

function SummaryField({ label, value }) {
  return (
    <div className="summary-card__row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function ControlStat({ label, value, helper }) {
  return (
    <article className="control-stat">
      <p className="control-stat__label">{label}</p>
      <strong className="control-stat__value">{value}</strong>
      {helper ? <p className="control-stat__helper">{helper}</p> : null}
    </article>
  )
}

function RouteComparisonCard({ route, index, winnerLabel, isSelected, onSelect }) {
  const style = getRouteStyle(route.route_label, index)
  const display = getRouteDisplay(route)
  const metrics = computeRouteMetrics(route)
  const badge = getRouteBadge(route, index, winnerLabel)

  return (
    <button
      type="button"
      className={`comparison-card ${isSelected ? 'comparison-card--selected' : ''}`}
      onClick={() => onSelect(route.route_label)}
      style={{ '--route-color': style.color, '--route-halo': style.halo }}
    >
      <div className="comparison-card__header">
        <div>
          <h3>{display.title}</h3>
          <p>{display.description}</p>
        </div>
        <span className={`route-badge route-badge--${badge.toLowerCase().replace(/[^a-z]/g, '')}`}>{badge}</span>
      </div>
      <div className="comparison-card__metric-row">
        <span>Connectivity {metrics.connectivityScore}/100</span>
        <span>Min {metrics.minScore}/100</span>
        <span>ETA {roundValue(route.travel_time_min, 1)} min</span>
      </div>
      <div className="comparison-card__progress">
        <div className="comparison-card__progress-fill" style={{ width: `${metrics.connectivityScore}%` }} />
      </div>
      <div className="comparison-card__footer">
        <span>Distance {roundValue(metrics.distanceKm, 1)} km</span>
        <span>Weak segments {metrics.weakSegments}</span>
        <span>Telemetry penalty {roundValue(metrics.telemetryPenalty * 10, 1)}</span>
        <span>Quality score {metrics.qualityScore}/100</span>
      </div>
    </button>
  )
}

function RouteToggleBar({ routes, selectedRouteLabel, onSelect }) {
  return (
    <div className="route-toggle-bar">
      <button
        type="button"
        className={`route-toggle-bar__button ${selectedRouteLabel === '' ? 'route-toggle-bar__button--active' : ''}`}
        onClick={() => onSelect('')}
      >
        Show all routes
      </button>
      {routes.map((route, index) => {
        const routeStyle = getRouteStyle(route.route_label, index)
        const isActive = selectedRouteLabel === route.route_label

        return (
          <button
            key={route.route_label}
            type="button"
            className={`route-toggle-bar__button ${isActive ? 'route-toggle-bar__button--active' : ''}`}
            style={{ '--route-color': routeStyle.color }}
            onClick={() => onSelect(route.route_label)}
          >
            <span className="route-toggle-bar__dot" />
            {getRouteDisplay(route).title}
          </button>
        )
      })}
    </div>
  )
}

function ProviderSnapshot({ towers, providerBaseline }) {
  const grouped = towers.reduce((accumulator, tower) => {
    accumulator[tower.provider] = (accumulator[tower.provider] || 0) + 1
    return accumulator
  }, {})

  const entries = Object.entries(grouped).sort((left, right) => right[1] - left[1])
  const max = Math.max(...entries.map(([, count]) => count), 1)

  return (
    <div className="provider-snapshot">
      {entries.map(([provider, count]) => {
        const active = providerBaseline === 'All providers' || provider === providerBaseline

        return (
          <div key={provider} className={`provider-snapshot__row ${active ? 'provider-snapshot__row--active' : ''}`}>
            <span>{provider}</span>
            <div className="provider-snapshot__track">
              <div className="provider-snapshot__fill" style={{ width: `${(count / max) * 100}%` }} />
            </div>
            <strong>{count}</strong>
          </div>
        )
      })}
    </div>
  )
}

function PredictionPanel({ prediction, speed, onSpeedChange }) {
  const nextRisk = prediction?.next_risk
  const toneClass =
    nextRisk?.severity === 'critical'
      ? 'prediction-panel--critical'
      : nextRisk?.severity === 'warning'
        ? 'prediction-panel--warning'
        : 'prediction-panel--clear'

  return (
    <section className={`prediction-panel ${toneClass}`}>
      <div className="prediction-panel__header">
        <div>
          <p className="eyebrow">Live Signal Risk</p>
          <h3>{nextRisk?.message ?? 'Prediction loading...'}</h3>
        </div>
        <label className="speed-control">
          <span>Simulation speed</span>
          <input type="range" min="10" max="80" value={speed} onChange={(event) => onSpeedChange(Number(event.target.value))} />
          <strong>{speed} km/h</strong>
        </label>
      </div>
      {nextRisk ? (
        <div className="prediction-panel__meta">
          <span>Severity: {nextRisk.severity}</span>
          <span>Distance ahead: {nextRisk.distance_m ?? '--'} m</span>
          <span>Min signal: {nextRisk.predicted_min_signal ?? '--'}</span>
          <span>Bandwidth: {nextRisk.predicted_bandwidth_mbps ?? '--'} Mbps</span>
          <span>Risk score: {nextRisk.predicted_risk_score ?? '--'}</span>
        </div>
      ) : null}
    </section>
  )
}

function NetworkHealth({ overview, summary }) {
  const bars = [
    { label: 'Avg signal', value: overview.avg_signal_mean, max: 100, tone: 'safe' },
    { label: 'Min signal', value: overview.min_signal_mean, max: 100, tone: 'warning' },
    { label: 'Bandwidth', value: overview.estimated_bandwidth_mean_mbps, max: 120, tone: 'primary' },
    { label: 'Risk score', value: overview.risk_score_mean, max: 1, tone: 'danger' },
  ]

  const total = Math.max(summary.safe_segments + summary.unsafe_segments, 1)
  const safeAngle = (summary.safe_segments / total) * 360

  return (
    <section className="section-panel section-panel--health">
      <div className="section-panel__header">
        <div>
          <h2>Network health</h2>
          <p>City-scale route readiness, bandwidth, and safety split from the live backend.</p>
        </div>
      </div>

      <div className="health-bars">
        {bars.map((bar) => (
          <div className="health-bars__row" key={bar.label}>
            <div className="health-bars__meta">
              <span>{bar.label}</span>
              <strong>{roundValue(bar.value, bar.max === 1 ? 3 : 1)}</strong>
            </div>
            <div className="health-bars__track">
              <div
                className={`health-bars__fill health-bars__fill--${bar.tone}`}
                style={{ width: `${Math.max(6, (bar.value / bar.max) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="health-ring">
        <div
          className="health-ring__chart"
          style={{ background: `conic-gradient(#60efb1 0deg ${safeAngle}deg, #ff7079 ${safeAngle}deg 360deg)` }}
        >
          <div className="health-ring__inner">
            <strong>{summary.safe_segments}</strong>
            <span>safe edges</span>
          </div>
        </div>
        <div className="health-ring__legend">
          <p><span className="legend-dot legend-dot--safe" />Safe: {summary.safe_segments}</p>
          <p><span className="legend-dot legend-dot--unsafe" />Unsafe: {summary.unsafe_segments}</p>
          <p><span className="legend-dot legend-dot--tower" />Dead-zone edges: {overview.dead_zone_segments}</p>
        </div>
      </div>
    </section>
  )
}

function MapPanel({ mapData, plannedRoutes, sourcePoint, destinationPoint, selectedRouteLabel, providerBaseline }) {
  const mapRef = useRef(null)
  const containerRef = useRef(null)
  const [mapError, setMapError] = useState('')

  useEffect(() => {
    let cancelled = false
    let overlays = []

    if (!containerRef.current || !mapData || !GOOGLE_MAPS_API_KEY) {
      return undefined
    }

    loadGoogleMaps(GOOGLE_MAPS_API_KEY)
      .then((maps) => {
        if (cancelled) return

        if (!mapRef.current) {
          mapRef.current = new maps.Map(containerRef.current, {
            center: { lat: 12.9716, lng: 77.5946 },
            zoom: 13,
            mapTypeControl: false,
            streetViewControl: false,
            fullscreenControl: false,
          })
        }

        const map = mapRef.current
        const bounds = new maps.LatLngBounds(
          { lat: mapData.bbox.lat_min, lng: mapData.bbox.lon_min },
          { lat: mapData.bbox.lat_max, lng: mapData.bbox.lon_max },
        )

        overlays.forEach((overlay) => overlay.setMap(null))
        overlays = []

        mapData.segments.forEach((segment) => {
          const color = segment.dead_zone_flag ? '#ff7079' : segment.safe_flag ? '#4fe1a0' : '#ffca68'
          overlays.push(
            new maps.Polyline({
              path: [
                { lat: segment.start_lat, lng: segment.start_lon },
                { lat: segment.end_lat, lng: segment.end_lon },
              ],
              geodesic: true,
              strokeColor: color,
              strokeOpacity: 0.18,
              strokeWeight: 1.4,
              map,
              zIndex: 1,
            }),
          )
        })

        plannedRoutes.forEach((route, index) => {
          const routeStyle = getRouteStyle(route.route_label, index)
          const path = route.path_geometry.map((point) => ({ lat: point.lat, lng: point.lon }))
          const isVisible = !selectedRouteLabel || route.route_label === selectedRouteLabel

          overlays.push(
            new maps.Polyline({
              path,
              geodesic: true,
              strokeColor: routeStyle.halo,
              strokeOpacity: isVisible ? 0.92 : 0.38,
              strokeWeight: isVisible ? routeStyle.weight + 3.4 : routeStyle.weight + 1.6,
              map,
              zIndex: isVisible ? 11 : 5,
            }),
          )
          overlays.push(
            new maps.Polyline({
              path,
              geodesic: true,
              strokeColor: routeStyle.color,
              strokeOpacity: isVisible ? 0.98 : 0.33,
              strokeWeight: isVisible ? routeStyle.weight : routeStyle.weight - 0.8,
              map,
              zIndex: isVisible ? 13 + index : 7 + index,
            }),
          )

          path.forEach((point) => bounds.extend(point))
        })

        mapData.towers.forEach((tower) => {
          const matchesProvider = providerBaseline === 'All providers' || tower.provider === providerBaseline
          const towerColor =
            tower.provider === 'Jio'
              ? '#ffb765'
              : tower.provider === 'Airtel'
                ? '#76d1ff'
                : tower.provider === 'Vi'
                  ? '#ff7ea8'
                  : '#92e595'

          overlays.push(
            new maps.Marker({
              position: { lat: tower.lat, lng: tower.lon },
              map,
              title: `${tower.provider} ${tower.radio_type}`,
              zIndex: matchesProvider ? 20 : 10,
              opacity: matchesProvider ? 1 : 0.45,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: matchesProvider ? 7.4 : 5.4,
                fillColor: towerColor,
                fillOpacity: matchesProvider ? 1 : 0.72,
                strokeColor: '#ffffff',
                strokeWeight: matchesProvider ? 2.4 : 1.4,
              },
            }),
          )
        })

        mapData.weak_zones.forEach((zone) => {
          overlays.push(
            new maps.Circle({
              center: { lat: zone.center_lat, lng: zone.center_lon },
              radius: zone.radius_m,
              map,
              strokeColor: '#ff7079',
              strokeOpacity: 0.86,
              strokeWeight: 2.2,
              fillColor: '#ff7079',
              fillOpacity: 0.14,
              zIndex: 4,
            }),
          )
        })

        if (sourcePoint) {
          bounds.extend({ lat: sourcePoint.lat, lng: sourcePoint.lon })
          overlays.push(
            new maps.Marker({
              position: { lat: sourcePoint.lat, lng: sourcePoint.lon },
              map,
              title: 'Source',
              zIndex: 30,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 11,
                fillColor: '#5ef2a9',
                fillOpacity: 1,
                strokeColor: '#ffffff',
                strokeWeight: 3,
              },
            }),
          )
        }

        if (destinationPoint) {
          bounds.extend({ lat: destinationPoint.lat, lng: destinationPoint.lon })
          overlays.push(
            new maps.Marker({
              position: { lat: destinationPoint.lat, lng: destinationPoint.lon },
              map,
              title: 'Destination',
              zIndex: 30,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 11,
                fillColor: '#ff8c8b',
                fillOpacity: 1,
                strokeColor: '#ffffff',
                strokeWeight: 3,
              },
            }),
          )
        }

        map.fitBounds(bounds, 72)
        setMapError('')
      })
      .catch((error) => {
        if (!cancelled) {
          setMapError(error instanceof Error ? error.message : 'Failed to load Google Maps.')
        }
      })

    return () => {
      cancelled = true
      overlays.forEach((overlay) => overlay.setMap(null))
    }
  }, [mapData, plannedRoutes, sourcePoint, destinationPoint, selectedRouteLabel, providerBaseline])

  if (!GOOGLE_MAPS_API_KEY) {
    return (
      <div className="map-panel">
        <div className="map-panel__placeholder">Add `VITE_GOOGLE_MAPS_API_KEY` to `frontend/.env` to render the live Google map.</div>
      </div>
    )
  }

  return (
    <div className="map-panel">
      <div ref={containerRef} className="google-map" />
      {mapError ? <p className="error-text">{mapError}</p> : null}
      <div className="map-legend">
        <span><i className="legend-line legend-line--safe" /> Safe network</span>
        <span><i className="legend-line legend-line--risk" /> Risk network</span>
        <span><i className="legend-line legend-line--dead" /> Dead-zone network</span>
        <span><i className="legend-line legend-line--route-safe" /> Safe route</span>
        <span><i className="legend-line legend-line--route-balanced" /> Balanced route</span>
        <span><i className="legend-line legend-line--route-fastest" /> Fastest route</span>
        <span><i className="legend-line legend-line--route-emergency" /> Emergency route</span>
        <span><i className="legend-dot legend-dot--tower" /> Tower</span>
        <span><i className="legend-dot legend-dot--source" /> Source</span>
        <span><i className="legend-dot legend-dot--destination" /> Destination</span>
      </div>
    </div>
  )
}

function App() {
  const [summary, setSummary] = useState(null)
  const [overview, setOverview] = useState(null)
  const [routes, setRoutes] = useState([])
  const [towers, setTowers] = useState([])
  const [zones, setZones] = useState([])
  const [mapData, setMapData] = useState(null)
  const [prediction, setPrediction] = useState(null)
  const [sourcePoint, setSourcePoint] = useState(null)
  const [destinationPoint, setDestinationPoint] = useState(null)
  const [source, setSource] = useState(DEFAULT_SOURCE)
  const [destination, setDestination] = useState(DEFAULT_DESTINATION)
  const [speed, setSpeed] = useState(35)
  const [providerBaseline, setProviderBaseline] = useState(DEFAULT_PROVIDER)
  const [connectivityBias, setConnectivityBias] = useState(DEFAULT_CONNECTIVITY_BIAS)
  const [selectedRouteLabel, setSelectedRouteLabel] = useState('')
  const [loading, setLoading] = useState(true)
  const [planning, setPlanning] = useState(false)
  const [error, setError] = useState('')

  const providerOptions = useMemo(() => {
    const providers = Array.from(new Set(towers.map((tower) => tower.provider).filter(Boolean))).sort()
    return ['All providers', ...providers.filter((provider) => provider !== 'All providers')]
  }, [towers])

  const sortedRoutes = useMemo(() => {
    const order = ['Fastest', 'Balanced', 'Safe', 'Emergency']
    return [...routes].sort((left, right) => order.indexOf(left.route_label) - order.indexOf(right.route_label))
  }, [routes])

  const winnerLabel = useMemo(() => getWinnerLabel(sortedRoutes, connectivityBias), [sortedRoutes, connectivityBias])
  const winnerRoute = useMemo(
    () => sortedRoutes.find((route) => route.route_label === winnerLabel) ?? sortedRoutes[0] ?? null,
    [sortedRoutes, winnerLabel],
  )
  const selectedRoute = useMemo(
    () => sortedRoutes.find((route) => route.route_label === (selectedRouteLabel || winnerLabel)) ?? winnerRoute,
    [sortedRoutes, selectedRouteLabel, winnerLabel, winnerRoute],
  )

  useEffect(() => {
    if (winnerLabel && selectedRouteLabel !== winnerLabel) {
      setSelectedRouteLabel(winnerLabel)
    }
  }, [winnerLabel])

  useEffect(() => {
    if (providerOptions.length && !providerOptions.includes(providerBaseline)) {
      setProviderBaseline(providerOptions.includes(DEFAULT_PROVIDER) ? DEFAULT_PROVIDER : providerOptions[0])
    }
  }, [providerOptions, providerBaseline])

  async function loadPlan(nextSource = source, nextDestination = destination) {
    setPlanning(true)
    setError('')

    try {
      const response = await fetch(
        `${API_BASE}/planner/plan?dataset=full&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}`,
      )

      if (!response.ok) {
        throw new Error('Could not plan a route for those places.')
      }

      const data = await response.json()
      const nextRoutes = data.routes ?? []
      const nextWinner = getWinnerLabel(nextRoutes, connectivityBias)

      setRoutes(nextRoutes)
      setSelectedRouteLabel(nextWinner)
      setSourcePoint(data.source)
      setDestinationPoint(data.destination)
      setMapData(data.map_context)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to plan route.')
    } finally {
      setPlanning(false)
    }
  }

  async function loadPrediction(nextSource = source, nextDestination = destination, nextSpeed = speed) {
    try {
      const response = await fetch(
        `${API_BASE}/planner/predict-risk?dataset=full&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}&speed_kmph=${nextSpeed}&progress_ratio=0`,
      )

      if (!response.ok) {
        throw new Error('Could not generate signal risk prediction.')
      }

      const data = await response.json()
      setPrediction(data.prediction)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to predict signal risk.')
    }
  }

  useEffect(() => {
    let active = true

    async function loadDashboard() {
      setLoading(true)
      setError('')

      try {
        const [summaryRes, overviewRes, towersRes, zonesRes] = await Promise.all([
          fetch(`${API_BASE}/datasets/full/summary`),
          fetch(`${API_BASE}/planner/overview?dataset=full`),
          fetch(`${API_BASE}/datasets/full/towers?limit=60`),
          fetch(`${API_BASE}/datasets/full/weak-zones`),
        ])

        if (![summaryRes, overviewRes, towersRes, zonesRes].every((response) => response.ok)) {
          throw new Error('Backend response was not successful.')
        }

        const [summaryData, overviewData, towersData, zonesData] = await Promise.all([
          summaryRes.json(),
          overviewRes.json(),
          towersRes.json(),
          zonesRes.json(),
        ])

        if (!active) return

        setSummary(summaryData)
        setOverview(overviewData)
        setTowers(towersData.items ?? [])
        setZones(zonesData.items ?? [])
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load dashboard.')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    loadDashboard()
    loadPlan(DEFAULT_SOURCE, DEFAULT_DESTINATION)
    loadPrediction(DEFAULT_SOURCE, DEFAULT_DESTINATION, speed)

    return () => {
      active = false
    }
  }, [])

  function handleSubmit(event) {
    event.preventDefault()
    loadPlan(source, destination)
    loadPrediction(source, destination, speed)
  }

  function handleSpeedChange(nextSpeed) {
    setSpeed(nextSpeed)
    loadPrediction(source, destination, nextSpeed)
  }

  function handleBiasChange(nextBias) {
    setConnectivityBias(nextBias)
  }

  const winnerMetrics = winnerRoute ? computeRouteMetrics(winnerRoute) : null
  const selectedDisplay = selectedRoute ? getRouteDisplay(selectedRoute) : null

  return (
    <main className="app-shell">
      <section className="top-grid">
        <section className="hero-card">
          <div className="hero-card__copy">
            <p className="eyebrow">Bengaluru pilot</p>
            <h1>Connectivity-first routing for a city-scale prototype</h1>
            <p className="hero-card__text">
              Trade ETA against network continuity, bandwidth, and dead-zone avoidance using the live Bengaluru routing graph.
              The planner, map, and comparison cards below all use the real backend response instead of a static mockup.
            </p>
          </div>
        </section>

        <aside className="summary-card">
          <SummaryField
            label="Pilot corridor"
            value={`${shortPlaceName(sourcePoint?.query || source)} -> ${shortPlaceName(destinationPoint?.query || destination)}`}
          />
          <SummaryField label="Current winner" value={winnerRoute ? getRouteDisplay(winnerRoute).title : 'Planning...'} />
          <SummaryField label="Connectivity bias" value={`${connectivityBias}%`} />
        </aside>
      </section>

      <section className="control-grid">
        <section className="section-panel">
          <div className="section-panel__header">
            <div>
              <h2>Routing controls</h2>
              <p>Move the slider to trade ETA for stronger network continuity and highlight one operator baseline on the map.</p>
            </div>
          </div>

          <form className="planner-form planner-form--stacked" onSubmit={handleSubmit}>
            <div className="field-grid">
              <label className="field">
                <span>Source</span>
                <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="Cubbon Park, Bengaluru" />
              </label>
              <label className="field">
                <span>Destination</span>
                <input
                  value={destination}
                  onChange={(event) => setDestination(event.target.value)}
                  placeholder="Indiranagar Metro Station, Bengaluru"
                />
              </label>
            </div>

            <div className="field-grid field-grid--controls">
              <label className="field">
                <span>Operator baseline</span>
                <select value={providerBaseline} onChange={(event) => setProviderBaseline(event.target.value)}>
                  {providerOptions.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </label>

              <button type="submit" className="plan-button">
                {planning ? 'Planning...' : 'Plan route'}
              </button>
            </div>

            <div className="bias-control">
              <div className="bias-control__header">
                <span>Connectivity vs ETA</span>
                <strong>{connectivityBias}%</strong>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={connectivityBias}
                onChange={(event) => handleBiasChange(Number(event.target.value))}
              />
              <div className="bias-control__labels">
                <span>Fastest</span>
                <span>Most connected</span>
              </div>
            </div>

            <div className="control-stats">
              <ControlStat
                label="Selected route"
                value={winnerRoute ? getRouteDisplay(winnerRoute).title : 'Planning...'}
                helper={winnerRoute?.safe_flag ? 'Safety threshold held' : 'Watch weak patches'}
              />
              <ControlStat
                label="Connectivity score"
                value={winnerMetrics ? `${winnerMetrics.connectivityScore}/100` : '--'}
                helper={selectedDisplay?.description}
              />
              <ControlStat
                label="ETA"
                value={winnerRoute ? `${roundValue(winnerRoute.travel_time_min, 1)} min` : '--'}
                helper="Live route travel time"
              />
              <ControlStat
                label="Distance"
                value={winnerMetrics ? `${roundValue(winnerMetrics.distanceKm, 1)} km` : '--'}
                helper={`${winnerMetrics?.weakSegments ?? '--'} weak segments on path`}
              />
            </div>
          </form>
        </section>

        <section className="section-panel">
          <div className="section-panel__header">
            <div>
              <h2>Build order</h2>
              <p>The first production steps after this live prototype is behaving well.</p>
            </div>
          </div>
          <ol className="build-order">
            {BUILD_ORDER.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </section>
      </section>

      <PredictionPanel prediction={prediction} speed={speed} onSpeedChange={handleSpeedChange} />

      <section className="comparison-layout">
        <section className="section-panel">
          <div className="section-panel__header">
            <div>
              <h2>Route comparison</h2>
              <p>Each route is scored from sampled connectivity, bandwidth, and dead-zone exposure along the path.</p>
            </div>
          </div>

          <div className="comparison-list">
            {sortedRoutes.map((route, index) => (
              <RouteComparisonCard
                key={route.route_label}
                route={route}
                index={index}
                winnerLabel={winnerLabel}
                isSelected={(selectedRouteLabel || winnerLabel) === route.route_label}
                onSelect={setSelectedRouteLabel}
              />
            ))}
          </div>
        </section>

        {overview && summary ? <NetworkHealth overview={overview} summary={summary} /> : null}
      </section>

      <section className="map-layout">
        <section className="section-panel section-panel--map">
          <div className="section-panel__header">
            <div>
              <h2>Central Bengaluru map</h2>
              <p>Road network, towers, weak zones, and the currently planned route overlays.</p>
            </div>
          </div>
          <RouteToggleBar routes={sortedRoutes} selectedRouteLabel={selectedRouteLabel} onSelect={setSelectedRouteLabel} />
          <MapPanel
            mapData={mapData}
            plannedRoutes={sortedRoutes}
            sourcePoint={sourcePoint}
            destinationPoint={destinationPoint}
            selectedRouteLabel={selectedRouteLabel}
            providerBaseline={providerBaseline}
          />
        </section>

        <section className="section-panel">
          <div className="section-panel__header">
            <div>
              <h2>Coverage focus</h2>
              <p>Provider mix and live weak-zone overlays in the same corridor you are routing through.</p>
            </div>
          </div>

          <ProviderSnapshot towers={towers} providerBaseline={providerBaseline} />

          <div className="zone-list">
            {zones.map((zone) => (
              <article key={zone.zone_id} className="zone-chip">
                <span className="zone-chip__type">{zone.zone_type}</span>
                <strong>{zone.zone_id}</strong>
                <span>{zone.reason}</span>
                <span className="zone-chip__meta">
                  {zone.severity} - attenuation {zone.attenuation_factor}
                </span>
              </article>
            ))}
          </div>

          <div className="status-stack">
            <p className="status-pill">{loading ? 'Loading dataset...' : 'Live backend connected'}</p>
            {sourcePoint && destinationPoint ? (
              <div className="geocode-card">
                <p><strong>Source:</strong> {sourcePoint.display_name}</p>
                <p><strong>Destination:</strong> {destinationPoint.display_name}</p>
              </div>
            ) : null}
            {error ? <p className="error-text">{error}</p> : null}
          </div>
        </section>
      </section>
    </main>
  )
}

export default App
