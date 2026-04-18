import { ABOUT_FORMULA } from '../lib/routing'

export default function About() {
  return (
    <section className="about-page">
      <div className="panel">
        <p className="section-kicker">about</p>
        <h2>Connectivity-aware safe routing</h2>
        <p className="about-page__copy">
          This prototype treats connectivity as a safety constraint for autonomous vehicles, not just a convenience layer.
          The route engine weighs travel time against signal continuity, weak zones, bandwidth, and predicted risk.
        </p>
      </div>

      <div className="about-grid">
        <div className="panel">
          <p className="section-kicker">signal model</p>
          <pre className="formula-card">{ABOUT_FORMULA}</pre>
          <p className="about-note">Latency risk is derived heuristically from connectivity quality and dead-zone exposure.</p>
        </div>

        <div className="panel">
          <p className="section-kicker">data sources</p>
          <ul className="about-list">
            <li>OSM-derived Bengaluru road graph</li>
            <li>OpenCellID-backed and cleaned tower dataset</li>
            <li>Manual weak-zone overlays</li>
            <li>Simulated feedback and environment modifiers</li>
          </ul>
        </div>

        <div className="panel">
          <p className="section-kicker">assumptions</p>
          <ul className="about-list">
            <li>Signal strength and bandwidth are modeled estimates, not live carrier measurements.</li>
            <li>V2X zones are represented as demo overlays.</li>
            <li>Safety-critical mode can block or heavily penalize risky routes.</li>
            <li>The alpha slider re-ranks the available route set between ETA-first and connectivity-first outcomes.</li>
          </ul>
        </div>
      </div>
    </section>
  )
}
