import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import Planner from './pages/Planner'
import Dashboard from './pages/Dashboard'
import AdaptiveMap from './pages/AdaptiveMap'
import Simulation from './pages/Simulation'
import { requestJson } from './services/api'
import {
  API_BASE,
  DEFAULT_DATASET,
  DEFAULT_CONNECTIVITY_BIAS,
  DEFAULT_DESTINATION,
  DEFAULT_PROVIDER,
  DEFAULT_SOURCE,
  PAGE_DEFS,
  getModeLabel,
  normalizeRouteRoles,
  scoreRoutesForAlpha,
} from './lib/routing'

const PLAN_SNAPSHOT_KEY = 'avroute:lastPlanSnapshot'

function AppHeader({ activePage, cityLabel, activeModeLabel, onPageChange }) {
  return (
    <header className="app-header">
      <div className="brand-block">
        <span className="brand-mark" />
        <div>
          <strong>AVRoute - connectivity-aware safe routing</strong>
        </div>
      </div>

      <nav className="top-nav">
        {PAGE_DEFS.map((page) => (
          <button
            key={page.id}
            type="button"
            className={`top-nav__link ${activePage === page.id ? 'top-nav__link--active' : ''}`}
            onClick={() => onPageChange(page.id)}
          >
            {page.label}
          </button>
        ))}
      </nav>

      <div className="header-status">{cityLabel} · {activeModeLabel}</div>
    </header>
  )
}

function nodeIndexFromProgress(route, progress) {
  const nodeCount = route?.path_nodes?.length ?? route?.path_geometry?.length ?? 0
  if (nodeCount <= 1) return 0
  return Math.min(nodeCount - 1, Math.floor(progress * (nodeCount - 1)))
}

function progressFromNodeIndex(route, nodeIndex) {
  const nodeCount = route?.path_nodes?.length ?? route?.path_geometry?.length ?? 0
  if (nodeCount <= 1) return 0
  return Math.min(0.98, Math.max(0, nodeIndex / (nodeCount - 1)))
}

function findNearestRouteNodeIndex(route, referencePoint) {
  const path = route?.path_geometry ?? []
  if (!path.length || !referencePoint) return 0

  let bestIndex = 0
  let bestDistance = Number.POSITIVE_INFINITY
  path.forEach((point, index) => {
    const distance = Math.hypot(Number(point.lat) - Number(referencePoint.lat), Number(point.lon) - Number(referencePoint.lon))
    if (distance < bestDistance) {
      bestDistance = distance
      bestIndex = index
    }
  })

  return bestIndex
}

function readPlanSnapshot() {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(PLAN_SNAPSHOT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writePlanSnapshot(snapshot) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(PLAN_SNAPSHOT_KEY, JSON.stringify(snapshot))
  } catch {
    // Ignore storage failures and keep runtime state working.
  }
}

function buildPlanSignature({
  dataset,
  source,
  destination,
  alpha,
  providerBaseline,
  applicationType,
  environmentType,
  numericThreshold,
}) {
  return JSON.stringify({
    dataset,
    source: String(source ?? '').trim().toLowerCase(),
    destination: String(destination ?? '').trim().toLowerCase(),
    alpha: Number(alpha).toFixed(2),
    providerBaseline,
    applicationType,
    environmentType,
    numericThreshold: Number(numericThreshold).toFixed(1),
  })
}

export default function App() {
  const initialPlanSnapshotRef = useRef(readPlanSnapshot())
  const planRequestIdRef = useRef(0)
  const predictionRequestIdRef = useRef(0)
  const selectionModeRef = useRef('auto')
  const autoPlanReadyRef = useRef(Boolean(initialPlanSnapshotRef.current?.routes?.length))
  const planAbortRef = useRef(null)
  const predictionAbortRef = useRef(null)
  const appliedRerouteRef = useRef('')
  const pnrTriggeredRef = useRef(false)
  const pnrPauseTimeoutRef = useRef(null)
  const inflightPlanSignatureRef = useRef('')
  const lastPlanSignatureRef = useRef(initialPlanSnapshotRef.current?.signature ?? '')

  const [activePage, setActivePage] = useState('planner')
  const [source, setSource] = useState(DEFAULT_SOURCE)
  const [destination, setDestination] = useState(DEFAULT_DESTINATION)
  const [committedSource, setCommittedSource] = useState(initialPlanSnapshotRef.current?.committedSource ?? DEFAULT_SOURCE)
  const [committedDestination, setCommittedDestination] = useState(initialPlanSnapshotRef.current?.committedDestination ?? DEFAULT_DESTINATION)
  const [providerBaseline, setProviderBaseline] = useState(DEFAULT_PROVIDER)
  const [environmentType, setEnvironmentType] = useState('normal')
  const [applicationType, setApplicationType] = useState('Navigation')
  const [minSignalThreshold, setMinSignalThreshold] = useState('-92 dBm')
  const [alpha, setAlpha] = useState(DEFAULT_CONNECTIVITY_BIAS)
  const [selectedMode, setSelectedMode] = useState('Safe')
  const [simulationProgress, setSimulationProgress] = useState(0.18)
  const [speed, setSpeed] = useState(35)
  const [simulationPlaying, setSimulationPlaying] = useState(false)
  const [isDemoLocked, setIsDemoLocked] = useState(false)
  const activeDataset = DEFAULT_DATASET

  const [summary, setSummary] = useState(null)
  const [overview, setOverview] = useState(null)
  const [mapData, setMapData] = useState(initialPlanSnapshotRef.current?.mapData ?? null)
  const [sourcePoint, setSourcePoint] = useState(initialPlanSnapshotRef.current?.sourcePoint ?? null)
  const [destinationPoint, setDestinationPoint] = useState(initialPlanSnapshotRef.current?.destinationPoint ?? null)
  const [routes, setRoutes] = useState(initialPlanSnapshotRef.current?.routes ?? [])
  const [towers, setTowers] = useState([])
  const [zones, setZones] = useState([])
  const [prediction, setPrediction] = useState(null)
  const [fallbackStatus, setFallbackStatus] = useState(null)
  const [rerouteBanner, setRerouteBanner] = useState(null)
  const [playbackEvent, setPlaybackEvent] = useState(null)
  const [demoRecommendedRouteLabel, setDemoRecommendedRouteLabel] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const providerOptions = useMemo(() => {
    const providers = Array.from(new Set(towers.map((tower) => tower.provider).filter(Boolean))).sort()
    return ['All providers', ...providers]
  }, [towers])

  const numericThreshold = Number.parseFloat(String(minSignalThreshold).replace(/[^\d.-]/g, '')) || -92
  const normalizedRoutes = useMemo(() => normalizeRouteRoles(routes), [routes])
  const rankedRoutes = useMemo(
    () =>
      scoreRoutesForAlpha(normalizedRoutes, alpha, {
        applicationType,
        providerBaseline,
        minSignalThresholdDbm: numericThreshold,
      }),
    [normalizedRoutes, alpha, applicationType, providerBaseline, numericThreshold],
  )
  const winnerRoute = useMemo(() => rankedRoutes[0] ?? null, [rankedRoutes])
  const demoStartRoute = useMemo(() => {
    if (!rankedRoutes.length) return null
    const routeByRisk = [...rankedRoutes].sort((left, right) => {
      const leftRisk =
        Number(Boolean(left.point_of_no_return)) * 10 +
        Number(left.dead_zone_count || 0) * 4 +
        Number(Boolean(left.threshold_breach)) * 3 +
        Number(left.risk_score || 0)
      const rightRisk =
        Number(Boolean(right.point_of_no_return)) * 10 +
        Number(right.dead_zone_count || 0) * 4 +
        Number(Boolean(right.threshold_breach)) * 3 +
        Number(right.risk_score || 0)
      return rightRisk - leftRisk
    })
    return routeByRisk[0]
  }, [rankedRoutes])
  const [selectedRouteLabel, setSelectedRouteLabel] = useState('')
  const selectedRoute = useMemo(
    () => rankedRoutes.find((route) => route.route_label === selectedRouteLabel) ?? winnerRoute,
    [rankedRoutes, selectedRouteLabel, winnerRoute],
  )

  function handleRouteSelection(routeLabel, options = {}) {
    selectionModeRef.current = options.manual ? 'manual' : 'auto'
    setSelectedRouteLabel(routeLabel)
    setSelectedMode(routeLabel)
  }

  useEffect(() => {
    if (isDemoLocked) return
    if (selectionModeRef.current !== 'auto') return
    if (!winnerRoute?.route_label) return
    if (selectedRouteLabel === winnerRoute.route_label) return
    handleRouteSelection(winnerRoute.route_label, { manual: false })
  }, [winnerRoute?.route_label, selectedRouteLabel, isDemoLocked])

  function resolveSafeRouteLabel(currentRouteLabel) {
    const safeRoute =
      demoRecommendedRouteLabel && demoRecommendedRouteLabel !== currentRouteLabel
        ? rankedRoutes.find((route) => route.route_label === demoRecommendedRouteLabel)
        : rankedRoutes.find((route) => route.route_label === 'Safe' && route.route_label !== currentRouteLabel) ??
          rankedRoutes.find((route) => route.route_label !== currentRouteLabel) ??
          null
    return safeRoute?.route_label ?? null
  }

  function triggerPnrReroute(route, hitNodeIndex) {
    const targetRouteLabel = resolveSafeRouteLabel(route?.route_label)
    if (!route || !targetRouteLabel) {
      setIsDemoLocked(false)
      return
    }

    const referencePoint = route.path_geometry?.[Math.min(hitNodeIndex, (route.path_geometry?.length ?? 1) - 1)] ?? null
    const targetRoute = rankedRoutes.find((item) => item.route_label === targetRouteLabel)
    const nearestNodeIndex = findNearestRouteNodeIndex(targetRoute, referencePoint)

    setSimulationPlaying(false)
    setRerouteBanner({
      title: 'Point of No Return reached — rerouting now',
      detail: `Switching from ${route.route_label} to ${targetRouteLabel} to avoid the dead zone ahead.`,
      routeLabel: targetRouteLabel,
      variant: 'pnr',
    })
    setPlaybackEvent({
      kind: 'reroute',
      title: 'PNR checkpoint hit',
      detail: `${route.route_label} -> ${targetRouteLabel} at node ${hitNodeIndex}.`,
    })

    if (pnrPauseTimeoutRef.current) {
      window.clearTimeout(pnrPauseTimeoutRef.current)
    }

    pnrPauseTimeoutRef.current = window.setTimeout(() => {
      handleRouteSelection(targetRouteLabel, { manual: false })
      setSimulationProgress(progressFromNodeIndex(targetRoute, nearestNodeIndex))
      setIsDemoLocked(false)
      setSimulationPlaying(true)
    }, 1500)
  }

  async function loadPrediction(nextSource = source, nextDestination = destination, nextSpeed = speed, nextRouteLabel = selectedRouteLabel) {
    const requestId = ++predictionRequestIdRef.current
    try {
      if (predictionAbortRef.current) {
        predictionAbortRef.current.abort()
      }
      const controller = new AbortController()
      predictionAbortRef.current = controller
      const data = await requestJson(
        `${API_BASE}/planner/predict-risk?dataset=${activeDataset}&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}&speed_kmph=${nextSpeed}&progress_ratio=${simulationProgress}&alpha=${alpha}&provider_baseline=${encodeURIComponent(providerBaseline)}&application_type=${encodeURIComponent(applicationType)}&environment_type=${encodeURIComponent(environmentType)}&min_signal_threshold_dbm=${numericThreshold}&route_label=${encodeURIComponent(nextRouteLabel || '')}`,
        { signal: controller.signal },
      )
      if (requestId !== predictionRequestIdRef.current) return
      setPrediction(data.prediction)
      setFallbackStatus(data.prediction?.fallback_status ?? null)
      setDemoRecommendedRouteLabel(data.recommended_route_label ?? null)

      const rerouteKey = [
        data.route_label ?? '',
        data.recommended_route_label ?? '',
        data.prediction?.current_segment_index ?? '',
      ].join(':')
      if (isDemoLocked) {
        return
      }
      if (
        activePage === 'simulation' &&
        data.should_reroute &&
        data.recommended_route_label &&
        data.recommended_route_label !== (nextRouteLabel || winnerRoute?.route_label || '') &&
        appliedRerouteRef.current !== rerouteKey
      ) {
        appliedRerouteRef.current = rerouteKey
        setRerouteBanner({
          title: 'Re-routing to maintain connectivity...',
          detail: data.reroute_reason || `Switching to the ${data.recommended_route_label} route.`,
          routeLabel: data.recommended_route_label,
        })
        setPlaybackEvent({
          kind: 'reroute',
          title: 'Auto reroute triggered',
          detail: `${data.route_label || 'Current'} -> ${data.recommended_route_label} at ${Math.round(simulationProgress * 100)}% progress`,
        })
        handleRouteSelection(data.recommended_route_label, { manual: false })
      }
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === 'AbortError') return
      if (requestId !== predictionRequestIdRef.current) return
      setError(loadError instanceof Error ? loadError.message : 'Failed to predict signal risk.')
    }
  }

  async function loadPlan(nextSource = source, nextDestination = destination, options = {}) {
    const { preserveSelection = false, force = false } = options
    const planSignature = buildPlanSignature({
      dataset: DEFAULT_DATASET,
      source: nextSource,
      destination: nextDestination,
      alpha,
      providerBaseline,
      applicationType,
      environmentType,
      numericThreshold,
    })

    if (!force && inflightPlanSignatureRef.current === planSignature) {
      return
    }

    if (!force && lastPlanSignatureRef.current === planSignature && routes.length && mapData) {
      setCommittedSource(nextSource)
      setCommittedDestination(nextDestination)
      return
    }

    const requestId = ++planRequestIdRef.current
    inflightPlanSignatureRef.current = planSignature
    setPlanning(true)
    setError('')
    try {
      if (planAbortRef.current) {
        planAbortRef.current.abort()
      }
      const controller = new AbortController()
      planAbortRef.current = controller
      const data = await requestJson(
        `${API_BASE}/planner/plan?dataset=${DEFAULT_DATASET}&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}&alpha=${alpha}&provider_baseline=${encodeURIComponent(providerBaseline)}&application_type=${encodeURIComponent(applicationType)}&environment_type=${encodeURIComponent(environmentType)}&min_signal_threshold_dbm=${numericThreshold}`,
        { signal: controller.signal },
      )
      if (requestId !== planRequestIdRef.current) return

      const nextRoutes = data.routes ?? []
      const availableLabels = new Set(nextRoutes.map((route) => route.route_label))
      const preferredRouteLabel =
        preserveSelection && selectedRouteLabel && availableLabels.has(selectedRouteLabel)
          ? selectedRouteLabel
          : data.recommended_route_label && availableLabels.has(data.recommended_route_label)
            ? data.recommended_route_label
            : nextRoutes[0]?.route_label ?? ''

      setRoutes(nextRoutes)
      setMapData(data.map_context)
      setSourcePoint(data.source)
      setDestinationPoint(data.destination)
      setCommittedSource(nextSource)
      setCommittedDestination(nextDestination)
      autoPlanReadyRef.current = true
      lastPlanSignatureRef.current = planSignature
      writePlanSnapshot({
        signature: planSignature,
        committedSource: nextSource,
        committedDestination: nextDestination,
        routes: nextRoutes,
        mapData: data.map_context,
        sourcePoint: data.source,
        destinationPoint: data.destination,
      })
      if (preferredRouteLabel) {
        handleRouteSelection(preferredRouteLabel, { manual: preserveSelection })
      }
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === 'AbortError') return
      if (requestId !== planRequestIdRef.current) return
      setError(loadError instanceof Error ? loadError.message : 'Failed to plan route.')
    } finally {
      if (inflightPlanSignatureRef.current === planSignature) {
        inflightPlanSignatureRef.current = ''
      }
      if (requestId === planRequestIdRef.current) {
        setPlanning(false)
      }
    }
  }

  useEffect(() => {
    let active = true

    async function loadDashboard() {
      setLoading(true)
      try {
        const [summaryRes, overviewRes, towersRes, zonesRes] = await Promise.all([
          requestJson(`${API_BASE}/datasets/${activeDataset}/summary`),
          requestJson(`${API_BASE}/planner/overview?dataset=${activeDataset}`),
          requestJson(`${API_BASE}/datasets/${activeDataset}/towers?limit=60`),
          requestJson(`${API_BASE}/datasets/${activeDataset}/weak-zones`),
        ])

        if (!active) return

        setSummary(summaryRes)
        setOverview(overviewRes)
        setTowers(towersRes.items ?? [])
        setZones(zonesRes.items ?? [])
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load dashboard.')
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadDashboard()

    return () => {
      active = false
    }
  }, [activeDataset])

  useEffect(() => {
    loadPlan(DEFAULT_SOURCE, DEFAULT_DESTINATION)
  }, [])

  useEffect(() => {
    if (!selectedRouteLabel && !winnerRoute?.route_label) return
    loadPrediction(committedSource, committedDestination, speed, selectedRouteLabel || winnerRoute?.route_label || '')
  }, [simulationProgress, selectedRouteLabel, speed, committedSource, committedDestination, winnerRoute?.route_label])

  useEffect(() => {
    if (!simulationPlaying) return undefined
    const intervalId = window.setInterval(() => {
      setSimulationProgress((current) => {
        if (!selectedRoute) {
          return current
        }

        const previousNodeIndex = nodeIndexFromProgress(selectedRoute, current)
        const next = Math.min(0.98, current + 0.015)
        const currentNodeIndex = nodeIndexFromProgress(selectedRoute, next)
        const pnrNodeIndex = selectedRoute?.pnr_node_index
        if (
          isDemoLocked &&
          pnrNodeIndex != null &&
          !pnrTriggeredRef.current &&
          pnrNodeIndex >= Math.min(previousNodeIndex, currentNodeIndex) &&
          pnrNodeIndex <= Math.max(previousNodeIndex, currentNodeIndex)
        ) {
          pnrTriggeredRef.current = true
          triggerPnrReroute(selectedRoute, pnrNodeIndex)
          return progressFromNodeIndex(selectedRoute, pnrNodeIndex)
        }
        if (next >= 0.98) {
          setSimulationPlaying(false)
        }
        return next
      })
    }, 260)
    return () => window.clearInterval(intervalId)
  }, [simulationPlaying, selectedRoute, isDemoLocked, demoRecommendedRouteLabel, rankedRoutes])

  useEffect(() => {
    if (activePage !== 'simulation') {
      setSimulationPlaying(false)
    }
  }, [activePage])

  useEffect(() => {
    if (simulationProgress < 0.12) {
      appliedRerouteRef.current = ''
      pnrTriggeredRef.current = false
      setRerouteBanner(null)
      setPlaybackEvent(null)
    }
  }, [simulationProgress])

  useEffect(() => {
    if (!rerouteBanner) return undefined
    const timeoutId = setTimeout(() => setRerouteBanner(null), 4200)
    return () => clearTimeout(timeoutId)
  }, [rerouteBanner])

  useEffect(() => {
    if (isDemoLocked) return undefined
    if (!autoPlanReadyRef.current || !committedSource || !committedDestination) return undefined

    const timeoutId = setTimeout(() => {
      selectionModeRef.current = 'auto'
      loadPlan(committedSource, committedDestination, { preserveSelection: false })
    }, 350)

    return () => clearTimeout(timeoutId)
  }, [alpha, providerBaseline, applicationType, environmentType, minSignalThreshold, isDemoLocked])

  useEffect(() => () => {
    if (pnrPauseTimeoutRef.current) {
      window.clearTimeout(pnrPauseTimeoutRef.current)
    }
  }, [])

  function handleSubmit() {
    selectionModeRef.current = 'auto'
    setSimulationPlaying(false)
    setIsDemoLocked(false)
    appliedRerouteRef.current = ''
    pnrTriggeredRef.current = false
    setRerouteBanner(null)
    setPlaybackEvent(null)
    setDemoRecommendedRouteLabel(null)
    setCommittedSource(source)
    setCommittedDestination(destination)
    loadPlan(source, destination, { preserveSelection: false, force: true })
  }

  function handleSimulationPlayPause() {
    if (simulationPlaying) {
      setSimulationPlaying(false)
      return
    }

    if (simulationProgress >= 0.98) {
      setSimulationProgress(0)
    }
    setSimulationPlaying(true)
  }

  function handleSimulationReplay() {
    setSimulationPlaying(false)
    setIsDemoLocked(false)
    appliedRerouteRef.current = ''
    pnrTriggeredRef.current = false
    setRerouteBanner(null)
    setPlaybackEvent({
      kind: 'replay',
      title: 'Playback reset',
      detail: 'Replay queued from the start of the route.',
    })
    setSimulationProgress(0)
    if (demoStartRoute?.route_label) {
      handleRouteSelection(demoStartRoute.route_label, { manual: true })
    }
  }

  function handleSimulationPlayDemo() {
    appliedRerouteRef.current = ''
    pnrTriggeredRef.current = false
    setRerouteBanner(null)
    setPlaybackEvent({
      kind: 'demo',
      title: 'Reroute demo armed',
      detail: `Playback will begin from ${demoStartRoute?.route_label ?? 'the riskiest available route'}.`,
    })
    setSimulationProgress(0)
    if (demoStartRoute?.route_label) {
      handleRouteSelection(demoStartRoute.route_label, { manual: true })
    }
    setDemoRecommendedRouteLabel(resolveSafeRouteLabel(demoStartRoute?.route_label ?? ''))
    setIsDemoLocked(demoStartRoute?.pnr_node_index != null)
    setSimulationPlaying(true)
  }

  const activeModeLabel = getModeLabel(selectedRouteLabel || winnerRoute?.route_label || selectedMode)
  const cityLabel = sourcePoint?.display_name?.includes('Bengaluru') ? 'Bengaluru' : 'Bengaluru'

  return (
    <main className="suite-shell">
      <AppHeader activePage={activePage} cityLabel={cityLabel} activeModeLabel={activeModeLabel} onPageChange={setActivePage} />

      {activePage === 'planner' ? (
        <Planner
          source={source}
          destination={destination}
          setSource={setSource}
          setDestination={setDestination}
          selectedMode={selectedMode}
          onModeSelect={(routeLabel) => handleRouteSelection(routeLabel, { manual: true })}
          alpha={alpha}
          onAlphaChange={setAlpha}
          providerBaseline={providerBaseline}
          providerOptions={providerOptions}
          onProviderChange={setProviderBaseline}
          applicationType={applicationType}
          onApplicationTypeChange={setApplicationType}
          minSignalThreshold={minSignalThreshold}
          onThresholdChange={setMinSignalThreshold}
          planning={planning}
          error={error}
          onSubmit={handleSubmit}
          cityLabel={cityLabel}
          activeModeLabel={activeModeLabel}
          routes={rankedRoutes}
          selectedRouteLabel={selectedRouteLabel}
          onSelectRoute={(routeLabel) => handleRouteSelection(routeLabel, { manual: true })}
          winnerRoute={winnerRoute}
          mapData={mapData}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          prediction={prediction}
          fallbackStatus={fallbackStatus}
        />
      ) : null}

      {activePage === 'dashboard' ? (
        <Dashboard
          routes={rankedRoutes}
          alpha={alpha}
          selectedRouteLabel={selectedRouteLabel}
          onSelectRoute={(routeLabel) => handleRouteSelection(routeLabel, { manual: true })}
        />
      ) : null}

      {activePage === 'adaptive-map' ? (
        <AdaptiveMap
          mapData={mapData}
          routes={rankedRoutes}
          selectedRouteLabel={selectedRouteLabel}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          providerBaseline={providerBaseline}
        />
      ) : null}

      {activePage === 'simulation' ? (
        <Simulation
          selectedRoute={selectedRoute}
          mapData={mapData}
          routes={rankedRoutes}
          selectedRouteLabel={selectedRouteLabel}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          providerBaseline={providerBaseline}
          applicationType={applicationType}
          progress={simulationProgress}
          onProgressChange={setSimulationProgress}
          fallbackStatus={fallbackStatus}
          rerouteBanner={rerouteBanner}
          playbackEvent={playbackEvent}
          isDemoLocked={isDemoLocked}
          isPlaying={simulationPlaying}
          onPlayPause={handleSimulationPlayPause}
          onReplay={handleSimulationReplay}
          onPlayDemo={handleSimulationPlayDemo}
          demoStartRouteLabel={demoStartRoute?.route_label ?? null}
        />
      ) : null}
    </main>
  )
}
