import MapCanvas from '../components/MapCanvas'
import { RouteCard, SignalMeter } from '../components/RouteWidgets'
import { computeRouteMetrics, getOfflineFallbackSuggestions, roundValue } from '../lib/routing'

function Legend() {
  const items = [
    ['safe route', 'legend-chip__line--safe'],
    ['risk route', 'legend-chip__line--risk'],
    ['unsafe route', 'legend-chip__line--unsafe'],
    ['strong signal', 'legend-chip__swatch--strong'],
    ['weak signal', 'legend-chip__swatch--weak'],
    ['tower', 'legend-chip__dot--tower'],
    ['dead zone', 'legend-chip__dot--dead'],
  ]

  return (
    <div className="map-legend-card">
      <p className="section-kicker">map legend</p>
      {items.map(([label, className]) => (
        <div key={label} className="legend-chip">
          <i className={className} />
          <span>{label}</span>
        </div>
      ))}
    </div>
  )
}

function DownloadRouteButton({ selectedRoute, source, destination }) {
  function handleDownload() {
    if (!selectedRoute) return

    const payload = {
      exported_at: new Date().toISOString(),
      source,
      destination,
      route_label: selectedRoute.route_label,
      travel_time_min: selectedRoute.travel_time_min,
      travel_time_s: selectedRoute.travel_time_s,
      distance_m: selectedRoute.length_m,
      avg_signal: selectedRoute.avg_signal,
      min_signal: selectedRoute.min_signal,
      estimated_bandwidth_mbps: selectedRoute.estimated_bandwidth_mbps,
      risk_score: selectedRoute.risk_score,
      dead_zone_count: selectedRoute.dead_zone_count,
      point_of_no_return: selectedRoute.point_of_no_return ?? null,
      path_geometry: selectedRoute.path_geometry ?? [],
      segments: selectedRoute.segments ?? [],
    }

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const safeLabel = String(selectedRoute.route_label || 'route').toLowerCase().replace(/\s+/g, '-')
    link.href = url
    link.download = `${safeLabel}-offline-route.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <button type="button" className="map-download-button" onClick={handleDownload} disabled={!selectedRoute}>
      download route
    </button>
  )
}

function FallbackCard({ fallbackStatus, selectedRoute }) {
  if (!fallbackStatus) return null

  const pulloverTarget = fallbackStatus.pullover_target
  const pnr = selectedRoute?.point_of_no_return

  return (
    <div className="panel fallback-card">
      <p className="section-kicker">fallback status</p>
      <div className="fallback-card__grid">
        <div><span>vehicle state</span><strong>{fallbackStatus.vehicle_state ?? '--'}</strong></div>
        <div><span>degradation</span><strong>{fallbackStatus.active_degradation_level ?? '--'}</strong></div>
        <div><span>dead-zone timer</span><strong>{roundValue(fallbackStatus.dead_zone_timer_s ?? 0, 1)} s</strong></div>
        <div><span>cloud features</span><strong>{fallbackStatus.cloud_features_enabled ? 'enabled' : 'disabled'}</strong></div>
      </div>
      {pnr ? (
        <p className="fallback-card__note">
          PNR armed at {pnr.lat.toFixed(5)}, {pnr.lon.toFixed(5)}
        </p>
      ) : (
        <p className="fallback-card__note">No point of no return detected on the selected route.</p>
      )}
      {pulloverTarget ? (
        <p className="fallback-card__note fallback-card__note--critical">
          Pull over target: {pulloverTarget.road_type} segment near {pulloverTarget.lat.toFixed(5)}, {pulloverTarget.lon.toFixed(5)}
        </p>
      ) : null}
      {fallbackStatus.last_event ? (
        <div className={`inline-alert ${fallbackStatus.last_event.event_type === 'VEHICLE_HALTED' ? 'inline-alert--critical' : ''}`}>
          <strong>{fallbackStatus.last_event.event_type.toLowerCase().replace(/_/g, ' ')}</strong>
          <span>{fallbackStatus.last_event.message}</span>
        </div>
      ) : null}
    </div>
  )
}

function OfflineFallbackCard({ selectedRoute, prediction, applicationType }) {
  const suggestions = getOfflineFallbackSuggestions(selectedRoute, prediction, applicationType)

  if (!suggestions.length) return null

  return (
    <div className="panel offline-fallback-card">
      <p className="section-kicker">offline fallback</p>
      <p className="offline-fallback-card__copy">
        This corridor has weak-signal risk, so the vehicle should prepare a low-connectivity backup plan.
      </p>
      <ul className="offline-fallback-card__list">
        {suggestions.map((suggestion) => (
          <li key={suggestion}>{suggestion}</li>
        ))}
      </ul>
    </div>
  )
}

export default function Planner({
  source,
  destination,
  setSource,
  setDestination,
  selectedMode,
  onModeSelect,
  alpha,
  onAlphaChange,
  providerBaseline,
  providerOptions,
  onProviderChange,
  applicationType,
  onApplicationTypeChange,
  minSignalThreshold,
  onThresholdChange,
  planning,
  error,
  onSubmit,
  cityLabel,
  activeModeLabel,
  routes,
  selectedRouteLabel,
  onSelectRoute,
  winnerRoute,
  mapData,
  sourcePoint,
  destinationPoint,
  prediction,
  fallbackStatus,
}) {
  const selectedRoute = routes.find((route) => route.route_label === selectedRouteLabel) ?? winnerRoute
  const metrics = selectedRoute ? computeRouteMetrics(selectedRoute) : null

  return (
    <section className="planner-page">
      <aside className="planner-sidebar">
        <div className="panel">
          <p className="section-kicker">route planner</p>
          <div className="field">
            <label>source</label>
            <div className="input-dot">
              <span className="input-dot__marker input-dot__marker--source" />
              <input value={source} onChange={(event) => setSource(event.target.value)} />
            </div>
          </div>
          <div className="field">
            <label>destination</label>
            <div className="input-dot">
              <span className="input-dot__marker input-dot__marker--destination" />
              <input value={destination} onChange={(event) => setDestination(event.target.value)} />
            </div>
          </div>
          <button type="button" className="primary-action" onClick={onSubmit}>
            {planning ? 'planning...' : 'update route'}
          </button>
          {error ? (
            <div className="inline-alert inline-alert--critical">
              <strong>planner error</strong>
              <span>{error}</span>
            </div>
          ) : null}
        </div>

        <div className="panel">
          <p className="section-kicker">routing mode</p>
          <div className="mode-grid">
            {['Fastest', 'Balanced', 'Safe', 'Emergency'].map((mode) => (
              <button
                key={mode}
                type="button"
                className={`mode-grid__button ${selectedMode === mode ? 'mode-grid__button--active' : ''}`}
                onClick={() => onModeSelect(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <p className="section-kicker">alpha</p>
          <div className="alpha-block">
            <div className="alpha-block__header">
              <span>a - connectivity vs. ETA</span>
              <strong>a = {alpha.toFixed(2)}</strong>
            </div>
            <input type="range" min="0" max="1" step="0.01" value={alpha} onChange={(event) => onAlphaChange(Number(event.target.value))} />
            <div className="alpha-block__labels">
              <span>time</span>
              <span>connectivity</span>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="field">
            <label>operator baseline</label>
            <select value={providerBaseline} onChange={(event) => onProviderChange(event.target.value)}>
              {providerOptions.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>AV application</label>
            <select value={applicationType} onChange={(event) => onApplicationTypeChange(event.target.value)}>
              {['Navigation', 'Telematics', 'Ride-hail', 'OTA Update'].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>minimum signal threshold</label>
            <input value={minSignalThreshold} onChange={(event) => onThresholdChange(event.target.value)} />
          </div>
        </div>

        <div className="status-banner">
          <strong>{cityLabel}</strong>
          <span>{activeModeLabel}</span>
        </div>
      </aside>

      <section className="planner-map-column">
        <div className="panel panel--map">
          <DownloadRouteButton selectedRoute={selectedRoute} source={source} destination={destination} />
          <MapCanvas
            mapData={mapData}
            routes={routes}
            selectedRouteLabel={selectedRouteLabel}
            sourcePoint={sourcePoint}
            destinationPoint={destinationPoint}
            providerBaseline={providerBaseline}
            showAllRoutes={false}
            showPnr
            fallbackStatus={fallbackStatus}
          />
          <Legend />
        </div>
      </section>

      <aside className="planner-compare-column">
        <FallbackCard fallbackStatus={fallbackStatus} selectedRoute={selectedRoute} />
        <OfflineFallbackCard selectedRoute={selectedRoute} prediction={prediction} applicationType={applicationType} />

        <div className="panel">
          <p className="section-kicker">route comparison</p>
          <div className="route-stack">
            {routes.slice(0, 4).map((route) => {
              const blockedText =
                route.route_label === 'Fastest' && activeModeLabel === 'safety-critical mode'
                  ? 'blocked - exceeds dead-zone threshold in safety-critical mode'
                  : ''

              return (
                <RouteCard
                  key={route.route_label}
                  route={route}
                  alpha={alpha}
                  selected={selectedRouteLabel === route.route_label}
                  onSelect={onSelectRoute}
                  blockedText={blockedText}
                />
              )
            })}
          </div>
        </div>

        <div className="panel">
          <p className="section-kicker">selected route</p>
          {selectedRoute ? (
            <div className="mini-metrics">
              <div><span>ETA</span><strong>{roundValue(selectedRoute.travel_time_min, 1)} min</strong></div>
              <div><span>signal</span><strong>{metrics.signalLow}-{metrics.signalHigh}%</strong></div>
              <div><span>dead zones</span><strong>{selectedRoute.dead_zone_count}</strong></div>
              <div><span>confidence</span><strong>{metrics.confidenceLow}-{metrics.confidenceHigh}%</strong></div>
            </div>
          ) : null}
          {selectedRoute ? <SignalMeter route={selectedRoute} /> : null}
          {prediction?.next_risk ? (
            <div className="inline-alert">
              <strong>live alert</strong>
              <span>{prediction.next_risk.message}</span>
            </div>
          ) : null}
          {fallbackStatus?.last_event ? (
            <div className="inline-alert">
              <strong>{fallbackStatus.last_event.event_type.toLowerCase().replace(/_/g, ' ')}</strong>
              <span>{fallbackStatus.last_event.message}</span>
            </div>
          ) : null}
        </div>
      </aside>
    </section>
  )
}
