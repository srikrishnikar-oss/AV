import MapCanvas from '../components/MapCanvas'

function HeatLegend() {
  return (
    <div className="heat-legend">
      <p className="section-kicker">signal layers</p>
      <div><span className="heat-legend__swatch heat-legend__swatch--strong" />strong coverage</div>
      <div><span className="heat-legend__swatch heat-legend__swatch--mid" />variable coverage</div>
      <div><span className="heat-legend__swatch heat-legend__swatch--weak" />weak coverage</div>
      <div><span className="heat-legend__swatch heat-legend__swatch--dead" />dead zone</div>
    </div>
  )
}

export default function AdaptiveMap({
  mapData,
  routes,
  selectedRouteLabel,
  sourcePoint,
  destinationPoint,
  providerBaseline,
}) {
  return (
    <section className="adaptive-map-page">
      <div className="panel panel--map panel--map-full">
        <div className="adaptive-map-page__header">
          <div>
            <p className="section-kicker">adaptive signal map</p>
            <h2>Signal map with overlays</h2>
          </div>
          <HeatLegend />
        </div>
        <MapCanvas
          mapData={mapData}
          routes={routes}
          selectedRouteLabel={selectedRouteLabel}
          sourcePoint={sourcePoint}
          destinationPoint={destinationPoint}
          providerBaseline={providerBaseline}
          showAllRoutes
          showPnr
        />
      </div>
    </section>
  )
}
