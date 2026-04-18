import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import Planner from './pages/Planner'
import Dashboard from './pages/Dashboard'
import AdaptiveMap from './pages/AdaptiveMap'
import Simulation from './pages/Simulation'
import About from './pages/About'
import {
  API_BASE,
  DEFAULT_CONNECTIVITY_BIAS,
  DEFAULT_DESTINATION,
  DEFAULT_PROVIDER,
  DEFAULT_SOURCE,
  PAGE_DEFS,
  getModeLabel,
  normalizeRouteRoles,
  scoreRoutesForAlpha,
} from './lib/routing'

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

export default function App() {
  const planRequestIdRef = useRef(0)
  const predictionRequestIdRef = useRef(0)
  const selectionModeRef = useRef('auto')
  const autoPlanReadyRef = useRef(false)
  const planAbortRef = useRef(null)
  const predictionAbortRef = useRef(null)

  const [activePage, setActivePage] = useState('planner')
  const [source, setSource] = useState(DEFAULT_SOURCE)
  const [destination, setDestination] = useState(DEFAULT_DESTINATION)
  const [committedSource, setCommittedSource] = useState(DEFAULT_SOURCE)
  const [committedDestination, setCommittedDestination] = useState(DEFAULT_DESTINATION)
  const [providerBaseline, setProviderBaseline] = useState(DEFAULT_PROVIDER)
  const [environmentType, setEnvironmentType] = useState('normal')
  const [applicationType, setApplicationType] = useState('Navigation')
  const [minSignalThreshold, setMinSignalThreshold] = useState('-92 dBm')
  const [alpha, setAlpha] = useState(DEFAULT_CONNECTIVITY_BIAS)
  const [selectedMode, setSelectedMode] = useState('Safe')
  const [simulationProgress, setSimulationProgress] = useState(0.18)
  const [speed, setSpeed] = useState(35)

  const [summary, setSummary] = useState(null)
  const [overview, setOverview] = useState(null)
  const [mapData, setMapData] = useState(null)
  const [sourcePoint, setSourcePoint] = useState(null)
  const [destinationPoint, setDestinationPoint] = useState(null)
  const [routes, setRoutes] = useState([])
  const [towers, setTowers] = useState([])
  const [zones, setZones] = useState([])
  const [prediction, setPrediction] = useState(null)
  const [fallbackStatus, setFallbackStatus] = useState(null)
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
    if (selectionModeRef.current !== 'auto') return
    if (!winnerRoute?.route_label) return
    if (selectedRouteLabel === winnerRoute.route_label) return
    handleRouteSelection(winnerRoute.route_label, { manual: false })
  }, [winnerRoute?.route_label, selectedRouteLabel])

  async function loadPrediction(nextSource = source, nextDestination = destination, nextSpeed = speed, nextRouteLabel = selectedRouteLabel) {
    const requestId = ++predictionRequestIdRef.current
    try {
      if (predictionAbortRef.current) {
        predictionAbortRef.current.abort()
      }
      const controller = new AbortController()
      predictionAbortRef.current = controller
      const response = await fetch(
        `${API_BASE}/planner/predict-risk?dataset=full&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}&speed_kmph=${nextSpeed}&progress_ratio=${simulationProgress}&alpha=${alpha}&provider_baseline=${encodeURIComponent(providerBaseline)}&application_type=${encodeURIComponent(applicationType)}&environment_type=${encodeURIComponent(environmentType)}&min_signal_threshold_dbm=${numericThreshold}&route_label=${encodeURIComponent(nextRouteLabel || '')}`,
        { signal: controller.signal },
      )
      if (!response.ok) throw new Error('Could not generate signal risk prediction.')
      const data = await response.json()
      if (requestId !== predictionRequestIdRef.current) return
      setPrediction(data.prediction)
      setFallbackStatus(data.prediction?.fallback_status ?? null)
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === 'AbortError') return
      if (requestId !== predictionRequestIdRef.current) return
      setError(loadError instanceof Error ? loadError.message : 'Failed to predict signal risk.')
    }
  }

  async function loadPlan(nextSource = source, nextDestination = destination, options = {}) {
    const { preserveSelection = false } = options
    const requestId = ++planRequestIdRef.current
    setPlanning(true)
    setError('')
    try {
      if (planAbortRef.current) {
        planAbortRef.current.abort()
      }
      const controller = new AbortController()
      planAbortRef.current = controller
      const response = await fetch(
        `${API_BASE}/planner/plan?dataset=full&source=${encodeURIComponent(nextSource)}&destination=${encodeURIComponent(nextDestination)}&alpha=${alpha}&provider_baseline=${encodeURIComponent(providerBaseline)}&application_type=${encodeURIComponent(applicationType)}&environment_type=${encodeURIComponent(environmentType)}&min_signal_threshold_dbm=${numericThreshold}`,
        { signal: controller.signal },
      )
      if (!response.ok) throw new Error('Could not plan a route for those places.')
      const data = await response.json()
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
      if (preferredRouteLabel) {
        handleRouteSelection(preferredRouteLabel, { manual: preserveSelection })
      }
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === 'AbortError') return
      if (requestId !== planRequestIdRef.current) return
      setError(loadError instanceof Error ? loadError.message : 'Failed to plan route.')
    } finally {
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
        if (active) setLoading(false)
      }
    }

    loadDashboard()
    loadPlan(DEFAULT_SOURCE, DEFAULT_DESTINATION)

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!selectedRouteLabel && !winnerRoute?.route_label) return
    loadPrediction(committedSource, committedDestination, speed, selectedRouteLabel || winnerRoute?.route_label || '')
  }, [simulationProgress, selectedRouteLabel, speed, committedSource, committedDestination, winnerRoute?.route_label])

  useEffect(() => {
    if (!autoPlanReadyRef.current || !committedSource || !committedDestination) return undefined

    const timeoutId = setTimeout(() => {
      selectionModeRef.current = 'auto'
      loadPlan(committedSource, committedDestination, { preserveSelection: false })
    }, 350)

    return () => clearTimeout(timeoutId)
  }, [alpha, providerBaseline, applicationType, environmentType, minSignalThreshold])

  function handleSubmit() {
    selectionModeRef.current = 'auto'
    setCommittedSource(source)
    setCommittedDestination(destination)
    loadPlan(source, destination, { preserveSelection: false })
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
          environmentType={environmentType}
          onEnvironmentTypeChange={setEnvironmentType}
          applicationType={applicationType}
          onApplicationTypeChange={setApplicationType}
          minSignalThreshold={minSignalThreshold}
          onThresholdChange={setMinSignalThreshold}
          planning={planning}
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
        />
      ) : null}

      {activePage === 'about' ? <About summary={summary} overview={overview} loading={loading} error={error} /> : null}
    </main>
  )
}
