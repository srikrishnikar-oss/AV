import { useEffect, useRef, useState } from 'react'
import { loadGoogleMaps } from '../googleMaps'
import { getRouteStyle } from '../lib/routing'

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY

function getHeatScale(segments) {
  const signals = segments
    .map((segment) => Number(segment.avg_signal || 0))
    .filter((value) => !Number.isNaN(value))
    .sort((left, right) => left - right)

  if (!signals.length) {
    return { strongThreshold: 68, mediumThreshold: 54 }
  }

  const strongIndex = Math.max(0, Math.floor(signals.length * 0.8) - 1)
  const mediumIndex = Math.max(0, Math.floor(signals.length * 0.45) - 1)
  return {
    strongThreshold: signals[strongIndex],
    mediumThreshold: signals[mediumIndex],
  }
}

function getHeatColor(avgSignal, scale) {
  const signal = Number(avgSignal || 0)
  if (signal >= scale.strongThreshold) return 'rgba(63, 185, 80, 0.52)'
  if (signal >= scale.mediumThreshold) return 'rgba(210, 153, 34, 0.34)'
  return 'rgba(248, 81, 73, 0.42)'
}

function getHeatStroke(avgSignal, scale) {
  const signal = Number(avgSignal || 0)
  if (signal >= scale.strongThreshold) return 'rgba(63, 185, 80, 0.78)'
  if (signal >= scale.mediumThreshold) return 'rgba(210, 153, 34, 0.58)'
  return 'rgba(248, 81, 73, 0.72)'
}

function sampleHeatSegments(segments, compact = false) {
  const step = compact ? 12 : 8
  return segments.filter((_, index) => index % step === 0)
}

function projectPoint(point, bbox, width, height, padding = 20) {
  const lonRange = Math.max(0.0001, bbox.lon_max - bbox.lon_min)
  const latRange = Math.max(0.0001, bbox.lat_max - bbox.lat_min)
  const x = padding + ((point.lon - bbox.lon_min) / lonRange) * (width - padding * 2)
  const y = height - padding - ((point.lat - bbox.lat_min) / latRange) * (height - padding * 2)
  return { x, y }
}

function pathToSvg(path, bbox, width, height) {
  return path
    .map((point, index) => {
      const projected = projectPoint(point, bbox, width, height)
      return `${index === 0 ? 'M' : 'L'} ${projected.x.toFixed(2)} ${projected.y.toFixed(2)}`
    })
    .join(' ')
}

function FallbackMapView({
  mapData,
  routes,
  selectedRouteLabel,
  sourcePoint,
  destinationPoint,
  showAllRoutes,
  fallbackStatus,
}) {
  if (!mapData) {
    return <div className="map-panel__placeholder">Map data is not available yet.</div>
  }

  const width = 1000
  const height = 720
  const selectedRoute = routes.find((route) => route.route_label === selectedRouteLabel) ?? routes[0] ?? null
  const effectiveSelectedRouteLabel = selectedRoute?.route_label ?? selectedRouteLabel
  const visibleRoutes = showAllRoutes ? routes : routes.filter((route) => route.route_label === effectiveSelectedRouteLabel)
  const heatSegments = sampleHeatSegments(mapData.segments)
  const heatScale = getHeatScale(mapData.segments)

  return (
    <div className="map-canvas map-canvas--fallback">
      <svg viewBox={`0 0 ${width} ${height}`} className="map-canvas__svg" role="img" aria-label="Fallback route map">
        <rect x="0" y="0" width={width} height={height} fill="#1c2128" />

        {heatSegments.map((segment) => {
          const startLat = Number(segment.start_lat)
          const startLon = Number(segment.start_lon)
          const endLat = Number(segment.end_lat)
          const endLon = Number(segment.end_lon)
          const center = projectPoint(
            { lat: startLat + (endLat - startLat) / 2, lon: startLon + (endLon - startLon) / 2 },
            mapData.bbox,
            width,
            height,
          )
          return (
            <circle
              key={`heat-${segment.segment_id}`}
              cx={center.x}
              cy={center.y}
              r="28"
              fill={getHeatColor(segment.avg_signal, heatScale)}
              stroke={getHeatStroke(segment.avg_signal, heatScale)}
              strokeWidth="1.1"
            />
          )
        })}

        {mapData.segments.map((segment) => {
          const start = projectPoint({ lat: Number(segment.start_lat), lon: Number(segment.start_lon) }, mapData.bbox, width, height)
          const end = projectPoint({ lat: Number(segment.end_lat), lon: Number(segment.end_lon) }, mapData.bbox, width, height)
          const color = Number(segment.dead_zone_flag) === 1 ? '#f85149' : Number(segment.safe_flag) === 1 ? '#3fb950' : '#d29922'
          return (
            <line
              key={`seg-${segment.segment_id}`}
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              stroke={color}
              strokeOpacity="0.18"
              strokeWidth="1.2"
            />
          )
        })}

        {mapData.weak_zones.map((zone) => {
          const center = projectPoint({ lat: Number(zone.center_lat), lon: Number(zone.center_lon) }, mapData.bbox, width, height)
          return (
            <circle
              key={`zone-${zone.zone_id}`}
              cx={center.x}
              cy={center.y}
              r="18"
              fill="rgba(248,81,73,0.08)"
              stroke="#f85149"
              strokeWidth="1.5"
              strokeDasharray="5 4"
            />
          )
        })}

        {visibleRoutes.map((route, index) => {
          const style = getRouteStyle(route.route_label, index)
          const d = pathToSvg(route.path_geometry, mapData.bbox, width, height)
          return (
            <path
              key={`route-${route.route_label}`}
              d={d}
              fill="none"
              stroke={style.color}
              strokeWidth={style.weight}
              strokeOpacity={route.route_label === effectiveSelectedRouteLabel || !effectiveSelectedRouteLabel ? 0.95 : 0.6}
              strokeDasharray={style.dash ? style.dash.join(' ') : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )
        })}

        {selectedRoute?.point_of_no_return ? (() => {
          const pnr = projectPoint(
            { lat: Number(selectedRoute.point_of_no_return.lat), lon: Number(selectedRoute.point_of_no_return.lon) },
            mapData.bbox,
            width,
            height,
          )
          return (
            <g>
              <circle cx={pnr.x} cy={pnr.y} r="10" fill="rgba(248,81,73,0.24)" stroke="#f85149" strokeWidth="2" />
              <text x={pnr.x + 12} y={pnr.y - 10} fill="#f85149" fontSize="12">point of no return</text>
            </g>
          )
        })() : null}

        {fallbackStatus?.pullover_target ? (() => {
          const stop = projectPoint(
            { lat: Number(fallbackStatus.pullover_target.lat), lon: Number(fallbackStatus.pullover_target.lon) },
            mapData.bbox,
            width,
            height,
          )
          return (
            <g>
              <path d={`M ${stop.x} ${stop.y - 10} L ${stop.x - 8} ${stop.y + 8} L ${stop.x + 8} ${stop.y + 8} Z`} fill="#f85149" />
              <text x={stop.x + 12} y={stop.y + 4} fill="#f85149" fontSize="12">pull over target</text>
            </g>
          )
        })() : null}

        {mapData.towers.map((tower) => {
          const point = projectPoint({ lat: Number(tower.lat), lon: Number(tower.lon) }, mapData.bbox, width, height)
          return <circle key={`tower-${tower.tower_id}`} cx={point.x} cy={point.y} r="4" fill="#d29922" />
        })}

        {sourcePoint ? (() => {
          const point = projectPoint({ lat: Number(sourcePoint.lat), lon: Number(sourcePoint.lon) }, mapData.bbox, width, height)
          return <circle cx={point.x} cy={point.y} r="6" fill="#3fb950" stroke="#8ddb9b" strokeWidth="2" />
        })() : null}

        {destinationPoint ? (() => {
          const point = projectPoint({ lat: Number(destinationPoint.lat), lon: Number(destinationPoint.lon) }, mapData.bbox, width, height)
          return <circle cx={point.x} cy={point.y} r="6" fill="#f85149" stroke="#ffb1a8" strokeWidth="2" />
        })() : null}
      </svg>
      <div className="map-panel__placeholder">Fallback map view active.</div>
    </div>
  )
}

export default function MapCanvas({
  mapData,
  routes,
  selectedRouteLabel,
  sourcePoint,
  destinationPoint,
  providerBaseline,
  showAllRoutes = true,
  showPnr = true,
  simulationPoint = null,
  compact = false,
  fallbackStatus = null,
}) {
  const mapRef = useRef(null)
  const containerRef = useRef(null)
  const [mapError, setMapError] = useState('')
  const selectedRoute = routes.find((route) => route.route_label === selectedRouteLabel) ?? routes[0] ?? null
  const effectiveSelectedRouteLabel = selectedRoute?.route_label ?? selectedRouteLabel

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
            styles: [
              { elementType: 'geometry', stylers: [{ color: '#1c2128' }] },
              { elementType: 'labels.text.fill', stylers: [{ color: '#c9d1d9' }] },
              { elementType: 'labels.text.stroke', stylers: [{ color: '#0d1117' }] },
              { featureType: 'poi', stylers: [{ visibility: 'off' }] },
              { featureType: 'transit', stylers: [{ visibility: 'off' }] },
              { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#30363d' }] },
              { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#11161c' }] },
            ],
          })
        }

        const map = mapRef.current
        const bounds = new maps.LatLngBounds(
          { lat: mapData.bbox.lat_min, lng: mapData.bbox.lon_min },
          { lat: mapData.bbox.lat_max, lng: mapData.bbox.lon_max },
        )

        overlays.forEach((overlay) => overlay.setMap(null))
        overlays = []
        const heatScale = getHeatScale(mapData.segments)

        sampleHeatSegments(mapData.segments, compact).forEach((segment) => {
          const center = {
            lat: Number(segment.start_lat) + (Number(segment.end_lat) - Number(segment.start_lat)) / 2,
            lng: Number(segment.start_lon) + (Number(segment.end_lon) - Number(segment.start_lon)) / 2,
          }
          overlays.push(
            new maps.Circle({
              center,
              radius: compact ? 95 : 150,
              map,
              strokeColor: getHeatStroke(segment.avg_signal, heatScale),
              strokeOpacity: 0.35,
              strokeWeight: 1.2,
              fillColor: getHeatColor(segment.avg_signal, heatScale),
              fillOpacity: 0.3,
              zIndex: 0,
            }),
          )
        })

        mapData.segments.forEach((segment) => {
          const color = segment.dead_zone_flag ? '#f85149' : segment.safe_flag ? '#3fb950' : '#d29922'
          overlays.push(
            new maps.Polyline({
              path: [
                { lat: segment.start_lat, lng: segment.start_lon },
                { lat: segment.end_lat, lng: segment.end_lon },
              ],
              geodesic: true,
              strokeColor: color,
              strokeOpacity: 0.18,
              strokeWeight: compact ? 1 : 1.3,
              map,
              zIndex: 1,
            }),
          )
        })

        const visibleRoutes = showAllRoutes ? routes : routes.filter((route) => route.route_label === effectiveSelectedRouteLabel)

        visibleRoutes.forEach((route, index) => {
          const routeStyle = getRouteStyle(route.route_label, index)
          const path = route.path_geometry.map((point) => ({ lat: point.lat, lng: point.lon }))
          const isSelected = route.route_label === effectiveSelectedRouteLabel || !effectiveSelectedRouteLabel

          overlays.push(
            new maps.Polyline({
              path,
              geodesic: true,
              strokeColor: routeStyle.color,
              strokeOpacity: routeStyle.blocked ? 0.4 : isSelected ? 0.98 : 0.62,
              strokeWeight: compact ? routeStyle.weight - 1.3 : routeStyle.weight,
              icons: routeStyle.dash
                ? [
                    {
                      icon: {
                        path: 'M 0,-1 0,1',
                        strokeOpacity: 1,
                        scale: 3,
                        strokeColor: routeStyle.color,
                      },
                      offset: '0',
                      repeat: `${routeStyle.dash[0] + routeStyle.dash[1]}px`,
                    },
                  ]
                : undefined,
              map,
              zIndex: isSelected ? 12 + index : 7 + index,
            }),
          )

          path.forEach((point) => bounds.extend(point))

          if (showPnr && route.route_label === effectiveSelectedRouteLabel) {
            const pnr = route.point_of_no_return
            if (pnr) {
              bounds.extend({ lat: pnr.lat, lng: pnr.lon })
              overlays.push(
                new maps.Marker({
                  position: { lat: pnr.lat, lng: pnr.lon },
                  map,
                  zIndex: 22,
                  icon: {
                    path: maps.SymbolPath.CIRCLE,
                    scale: 9,
                    fillColor: '#f85149',
                    fillOpacity: 0.34,
                    strokeColor: '#f85149',
                    strokeWeight: 2.4,
                  },
                  label: {
                    text: 'point of no return',
                    color: '#f85149',
                    fontSize: '11px',
                    fontWeight: '500',
                  },
                }),
              )
            }
          }
        })

        if (fallbackStatus?.pullover_target) {
          const stop = fallbackStatus.pullover_target
          bounds.extend({ lat: stop.lat, lng: stop.lon })
          overlays.push(
            new maps.Marker({
              position: { lat: stop.lat, lng: stop.lon },
              map,
              zIndex: 26,
              icon: {
                path: maps.SymbolPath.BACKWARD_CLOSED_ARROW,
                scale: 6,
                fillColor: '#f85149',
                fillOpacity: 1,
                strokeColor: '#ffb1a8',
                strokeWeight: 1.8,
              },
              label: {
                text: 'pull over target',
                color: '#f85149',
                fontSize: '11px',
                fontWeight: '500',
              },
            }),
          )
        }

        if (fallbackStatus?.last_event?.event_type === 'VEHICLE_HALTED' && fallbackStatus?.last_known_gps) {
          overlays.push(
            new maps.Circle({
              center: { lat: fallbackStatus.last_known_gps.lat, lng: fallbackStatus.last_known_gps.lon },
              radius: 60,
              map,
              strokeColor: '#f85149',
              strokeOpacity: 0.95,
              strokeWeight: 2,
              fillColor: '#f85149',
              fillOpacity: 0.12,
              zIndex: 28,
            }),
          )
        }

        mapData.weak_zones.forEach((zone) => {
          overlays.push(
            new maps.Circle({
              center: { lat: zone.center_lat, lng: zone.center_lon },
              radius: zone.radius_m,
              map,
              strokeColor: '#f85149',
              strokeOpacity: 0.7,
              strokeWeight: 1.4,
              fillColor: '#f85149',
              fillOpacity: 0.08,
              zIndex: 4,
            }),
          )
        })

        const bbox = mapData.bbox
        const v2xRects = [
          {
            north: bbox.lat_max - 0.006,
            south: bbox.lat_max - 0.012,
            east: bbox.lon_max - 0.006,
            west: bbox.lon_max - 0.018,
            label: 'V2X zone',
          },
          {
            north: bbox.lat_min + 0.016,
            south: bbox.lat_min + 0.008,
            east: bbox.lon_min + 0.024,
            west: bbox.lon_min + 0.01,
            label: 'V2X zone',
          },
        ]

        v2xRects.forEach((rect) => {
          overlays.push(
            new maps.Rectangle({
              bounds: {
                north: rect.north,
                south: rect.south,
                east: rect.east,
                west: rect.west,
              },
              map,
              strokeColor: '#58a6ff',
              strokeOpacity: 0.82,
              strokeWeight: 1.2,
              fillColor: '#58a6ff',
              fillOpacity: 0.06,
              zIndex: 3,
            }),
          )
          overlays.push(
            new maps.Marker({
              position: { lat: (rect.north + rect.south) / 2, lng: (rect.east + rect.west) / 2 },
              map,
              zIndex: 4,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 0,
              },
              label: {
                text: rect.label,
                color: '#58a6ff',
                fontSize: '11px',
                fontWeight: '500',
              },
            }),
          )
        })

        mapData.towers.forEach((tower) => {
          const matchesProvider = providerBaseline === 'All providers' || tower.provider === providerBaseline
          overlays.push(
            new maps.Marker({
              position: { lat: tower.lat, lng: tower.lon },
              map,
              zIndex: matchesProvider ? 18 : 9,
              opacity: matchesProvider ? 1 : 0.45,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: matchesProvider ? 5.4 : 4.1,
                fillColor: '#d29922',
                fillOpacity: 1,
                strokeColor: '#f0c674',
                strokeWeight: 1.3,
              },
            }),
          )
        })

        if (sourcePoint) {
          bounds.extend({ lat: sourcePoint.lat, lng: sourcePoint.lon })
          overlays.push(
            new maps.Marker({
              position: { lat: sourcePoint.lat, lng: sourcePoint.lon },
              map,
              zIndex: 30,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 7,
                fillColor: '#3fb950',
                fillOpacity: 1,
                strokeColor: '#8ddb9b',
                strokeWeight: 2,
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
              zIndex: 30,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 7,
                fillColor: '#f85149',
                fillOpacity: 1,
                strokeColor: '#ffb1a8',
                strokeWeight: 2,
              },
            }),
          )
        }

        if (simulationPoint) {
          overlays.push(
            new maps.Marker({
              position: { lat: simulationPoint.lat, lng: simulationPoint.lon },
              map,
              zIndex: 34,
              icon: {
                path: maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: '#58a6ff',
                fillOpacity: 1,
                strokeColor: '#d0e2ff',
                strokeWeight: 2,
              },
            }),
          )
        }

        map.fitBounds(bounds, compact ? 44 : 54)
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
  }, [mapData, routes, effectiveSelectedRouteLabel, sourcePoint, destinationPoint, providerBaseline, showAllRoutes, showPnr, compact, simulationPoint, fallbackStatus])

  if (!GOOGLE_MAPS_API_KEY) {
    return (
      <FallbackMapView
        mapData={mapData}
        routes={routes}
        selectedRouteLabel={effectiveSelectedRouteLabel}
        sourcePoint={sourcePoint}
        destinationPoint={destinationPoint}
        showAllRoutes={showAllRoutes}
        fallbackStatus={fallbackStatus}
      />
    )
  }

  return (
    <div className="map-canvas-wrap">
      {!mapError ? <div ref={containerRef} className={`map-canvas ${compact ? 'map-canvas--compact' : ''}`} /> : null}
      {mapError ? (
        <FallbackMapView
          mapData={mapData}
          routes={routes}
          selectedRouteLabel={effectiveSelectedRouteLabel}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          showAllRoutes={showAllRoutes}
          fallbackStatus={fallbackStatus}
        />
      ) : null}
      {mapError ? <p className="error-text">{mapError}</p> : null}
    </div>
  )
}
