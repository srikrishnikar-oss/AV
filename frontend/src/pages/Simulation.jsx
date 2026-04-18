import MapCanvas from '../components/MapCanvas'
import { buildSimulationState, getOfflineFallbackSuggestions, roundValue } from '../lib/routing'

export default function Simulation({
  selectedRoute,
  mapData,
  routes,
  selectedRouteLabel,
  sourcePoint,
  destinationPoint,
  providerBaseline,
  applicationType,
  progress,
  onProgressChange,
  fallbackStatus,
}) {
  const state = buildSimulationState(selectedRoute, progress)
  const offlineSuggestions = getOfflineFallbackSuggestions(selectedRoute, null, applicationType)

  return (
    <section className="simulation-page">
      <div className="panel">
        <p className="section-kicker">simulation</p>
        <div className="simulation-controls">
          <label>
            progress
            <input type="range" min="0" max="1" step="0.01" value={progress} onChange={(event) => onProgressChange(Number(event.target.value))} />
          </label>
          <div className="simulation-metrics">
            <div><span>signal</span><strong>{state ? `${state.signal}%` : '--'}</strong></div>
            <div><span>latency risk</span><strong>{state ? roundValue(state.latencyRisk, 2) : '--'}</strong></div>
            <div><span>bandwidth</span><strong>{state ? `${state.bandwidth} Mbps` : '--'}</strong></div>
            <div><span>autonomy</span><strong>{state?.autonomyLevel ?? '--'}</strong></div>
            <div><span>ETA left</span><strong>{state ? `${roundValue(state.etaRemainingMin, 1)} min` : '--'}</strong></div>
            <div><span>fallback state</span><strong>{fallbackStatus?.vehicle_state ?? '--'}</strong></div>
            <div><span>dead-zone timer</span><strong>{fallbackStatus ? `${roundValue(fallbackStatus.dead_zone_timer_s, 1)} s` : '--'}</strong></div>
          </div>
        </div>
        {fallbackStatus?.last_event ? (
          <div className="inline-alert">
            <strong>{fallbackStatus.last_event.event_type.toLowerCase().replace(/_/g, ' ')}</strong>
            <span>{fallbackStatus.last_event.message}</span>
          </div>
        ) : null}
        {offlineSuggestions.length ? (
          <div className="inline-alert">
            <strong>offline fallback suggestion</strong>
            <span>{offlineSuggestions.join(' ')}</span>
          </div>
        ) : null}
      </div>

      <div className="panel panel--map">
        {fallbackStatus?.last_event?.event_type === 'VEHICLE_HALTED' ? (
          <div className="inline-alert inline-alert--critical">
            <strong>pull over triggered</strong>
            <span>{fallbackStatus.last_event.message}</span>
          </div>
        ) : null}
        <MapCanvas
          mapData={mapData}
          routes={routes}
          selectedRouteLabel={selectedRouteLabel}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          providerBaseline={providerBaseline}
          showAllRoutes={false}
          showPnr
          simulationPoint={state?.point ?? null}
          fallbackStatus={fallbackStatus}
        />
      </div>
    </section>
  )
}
