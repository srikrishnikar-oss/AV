import { ConfidenceLine, DegradationStrip, RouteCard } from '../components/RouteWidgets'
import { computeRouteMetrics, roundValue } from '../lib/routing'

function ComparisonTable({ routes }) {
  return (
    <div className="comparison-table">
      <table>
        <thead>
          <tr>
            <th>route</th>
            <th>ETA</th>
            <th>connectivity</th>
            <th>dead zones</th>
            <th>degradation</th>
            <th>status</th>
            <th>PNR</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route) => {
            const metrics = computeRouteMetrics(route)
            return (
              <tr key={route.route_label}>
                <td>{route.route_label}</td>
                <td>{roundValue(route.travel_time_min, 1)} min</td>
                <td>{metrics.confidenceLow}-{metrics.confidenceHigh}%</td>
                <td>{route.dead_zone_count}</td>
                <td><DegradationStrip route={route} /></td>
                <td>{route.safe_flag ? 'safe' : 'warning'}</td>
                <td>{route.dead_zone_count ? 'before Ulsoor corridor' : 'not needed'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function Dashboard({ routes, alpha, selectedRouteLabel, onSelectRoute }) {
  return (
    <section className="dashboard-page">
      <div className="panel">
        <p className="section-kicker">route cards</p>
        <div className="dashboard-cards">
          {routes.map((route) => (
            <div key={route.route_label} className="dashboard-cards__item">
              <RouteCard
                route={route}
                alpha={alpha}
                selected={selectedRouteLabel === route.route_label}
                onSelect={onSelectRoute}
              />
              <ConfidenceLine route={route} />
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <p className="section-kicker">comparison table</p>
        <ComparisonTable routes={routes} />
      </div>
    </section>
  )
}
