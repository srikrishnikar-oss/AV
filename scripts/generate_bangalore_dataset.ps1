param(
    [string]$OutputRoot = "C:\Users\srikr\Desktop\AV\data"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-DistanceMeters {
    param(
        [double]$Lat1,
        [double]$Lon1,
        [double]$Lat2,
        [double]$Lon2
    )

    $earthRadius = 6371000.0
    $dLat = ($Lat2 - $Lat1) * [Math]::PI / 180.0
    $dLon = ($Lon2 - $Lon1) * [Math]::PI / 180.0
    $a = [Math]::Sin($dLat / 2.0) * [Math]::Sin($dLat / 2.0) +
         [Math]::Cos($Lat1 * [Math]::PI / 180.0) * [Math]::Cos($Lat2 * [Math]::PI / 180.0) *
         [Math]::Sin($dLon / 2.0) * [Math]::Sin($dLon / 2.0)
    $c = 2.0 * [Math]::Atan2([Math]::Sqrt($a), [Math]::Sqrt(1.0 - $a))
    return $earthRadius * $c
}

function Clamp {
    param(
        [double]$Value,
        [double]$Min,
        [double]$Max
    )

    if ($Value -lt $Min) { return $Min }
    if ($Value -gt $Max) { return $Max }
    return $Value
}

Ensure-Directory -Path $OutputRoot
$rawDir = Join-Path $OutputRoot "raw"
$processedDir = Join-Path $OutputRoot "processed"
Ensure-Directory -Path $rawDir
Ensure-Directory -Path $processedDir

$cityCenterLat = 12.9716
$cityCenterLon = 77.5946
$gridSize = 16
$latStep = 0.0040
$lonStep = 0.0045
$latStart = $cityCenterLat - (($gridSize - 1) * $latStep / 2.0)
$lonStart = $cityCenterLon - (($gridSize - 1) * $lonStep / 2.0)

$nodes = @{}
for ($row = 0; $row -lt $gridSize; $row++) {
    for ($col = 0; $col -lt $gridSize; $col++) {
        $nodeId = "N{0:D3}" -f (($row * $gridSize) + $col + 1)
        $nodes[$nodeId] = [PSCustomObject]@{
            node_id = $nodeId
            row = $row
            col = $col
            lat = [Math]::Round($latStart + ($row * $latStep), 6)
            lon = [Math]::Round($lonStart + ($col * $lonStep), 6)
        }
    }
}

$roadSegments = New-Object System.Collections.Generic.List[object]
$segmentCounter = 1

for ($row = 0; $row -lt $gridSize; $row++) {
    for ($col = 0; $col -lt $gridSize; $col++) {
        $nodeId = "N{0:D3}" -f (($row * $gridSize) + $col + 1)
        $node = $nodes[$nodeId]

        if ($col -lt ($gridSize - 1)) {
            $eastId = "N{0:D3}" -f (($row * $gridSize) + $col + 2)
            $eastNode = $nodes[$eastId]
            $roadType = if ($row % 5 -eq 0) { "primary" } elseif ($row % 3 -eq 0) { "secondary" } else { "residential" }
            $speedKmh = switch ($roadType) {
                "primary" { 42 }
                "secondary" { 32 }
                default { 24 }
            }
            $lengthM = [Math]::Round((Get-DistanceMeters -Lat1 $node.lat -Lon1 $node.lon -Lat2 $eastNode.lat -Lon2 $eastNode.lon), 2)
            $travelTimeS = [Math]::Round(($lengthM / ($speedKmh * 1000.0 / 3600.0)), 2)
            $roadSegments.Add([PSCustomObject]@{
                segment_id = "S{0:D4}" -f $segmentCounter
                start_node = $node.node_id
                end_node = $eastNode.node_id
                start_lat = $node.lat
                start_lon = $node.lon
                end_lat = $eastNode.lat
                end_lon = $eastNode.lon
                midpoint_lat = [Math]::Round((($node.lat + $eastNode.lat) / 2.0), 6)
                midpoint_lon = [Math]::Round((($node.lon + $eastNode.lon) / 2.0), 6)
                length_m = $lengthM
                travel_time_s = $travelTimeS
                road_type = $roadType
            })
            $segmentCounter++
        }

        if ($row -lt ($gridSize - 1)) {
            $southId = "N{0:D3}" -f (((($row + 1) * $gridSize) + $col) + 1)
            $southNode = $nodes[$southId]
            $roadType = if ($col % 5 -eq 0) { "primary" } elseif ($col % 3 -eq 0) { "secondary" } else { "residential" }
            $speedKmh = switch ($roadType) {
                "primary" { 40 }
                "secondary" { 30 }
                default { 22 }
            }
            $lengthM = [Math]::Round((Get-DistanceMeters -Lat1 $node.lat -Lon1 $node.lon -Lat2 $southNode.lat -Lon2 $southNode.lon), 2)
            $travelTimeS = [Math]::Round(($lengthM / ($speedKmh * 1000.0 / 3600.0)), 2)
            $roadSegments.Add([PSCustomObject]@{
                segment_id = "S{0:D4}" -f $segmentCounter
                start_node = $node.node_id
                end_node = $southNode.node_id
                start_lat = $node.lat
                start_lon = $node.lon
                end_lat = $southNode.lat
                end_lon = $southNode.lon
                midpoint_lat = [Math]::Round((($node.lat + $southNode.lat) / 2.0), 6)
                midpoint_lon = [Math]::Round((($node.lon + $southNode.lon) / 2.0), 6)
                length_m = $lengthM
                travel_time_s = $travelTimeS
                road_type = $roadType
            })
            $segmentCounter++
        }
    }
}

$providers = @("Jio", "Airtel", "Vi", "BSNL")
$radioCycle = @("5G", "4G", "4G", "3G")
$towerCount = 45
$towers = New-Object System.Collections.Generic.List[object]

for ($index = 0; $index -lt $towerCount; $index++) {
    $row = ($index * 7) % $gridSize
    $col = ($index * 11) % $gridSize
    $latOffset = ((($index % 3) - 1) * 0.0012)
    $lonOffset = (((($index + 1) % 3) - 1) * 0.0015)
    $provider = $providers[$index % $providers.Count]
    $radioType = $radioCycle[$index % $radioCycle.Count]
    $baseStrength = switch ($radioType) {
        "5G" { 92 - (($index % 4) * 2) }
        "4G" { 82 - (($index % 5) * 2) }
        default { 62 - (($index % 3) * 2) }
    }
    $coverageRadius = switch ($radioType) {
        "5G" { 1100 + (($index % 4) * 100) }
        "4G" { 2200 + (($index % 5) * 120) }
        default { 3400 + (($index % 4) * 150) }
    }
    $towerLat = [Math]::Round(($latStart + ($row * $latStep) + $latOffset), 6)
    $towerLon = [Math]::Round(($lonStart + ($col * $lonStep) + $lonOffset), 6)
    $towers.Add([PSCustomObject]@{
        tower_id = "T{0:D3}" -f ($index + 1)
        lat = $towerLat
        lon = $towerLon
        provider = $provider
        radio_type = $radioType
        base_strength = $baseStrength
        coverage_radius_m = $coverageRadius
    })
}

$weakZones = @(
    [PSCustomObject]@{ zone_id = "Z01"; center_lat = 12.9632; center_lon = 77.5712; radius_m = 320; zone_type = "underpass"; severity = "high"; attenuation_factor = 0.35; reason = "KR Market underpass cluster" },
    [PSCustomObject]@{ zone_id = "Z02"; center_lat = 12.9904; center_lon = 77.6039; radius_m = 420; zone_type = "urban_canyon"; severity = "medium"; attenuation_factor = 0.68; reason = "CBD high-rise interference" },
    [PSCustomObject]@{ zone_id = "Z03"; center_lat = 12.9486; center_lon = 77.5842; radius_m = 520; zone_type = "sparse_area"; severity = "high"; attenuation_factor = 0.42; reason = "Patchy southern edge coverage" },
    [PSCustomObject]@{ zone_id = "Z04"; center_lat = 12.9792; center_lon = 77.5481; radius_m = 300; zone_type = "tunnel"; severity = "high"; attenuation_factor = 0.20; reason = "Rail underpass signal attenuation" },
    [PSCustomObject]@{ zone_id = "Z05"; center_lat = 12.9549; center_lon = 77.6278; radius_m = 390; zone_type = "high_interference"; severity = "medium"; attenuation_factor = 0.60; reason = "Dense office cluster reflections" },
    [PSCustomObject]@{ zone_id = "Z06"; center_lat = 12.9998; center_lon = 77.5675; radius_m = 460; zone_type = "sparse_area"; severity = "medium"; attenuation_factor = 0.72; reason = "North-west fringe coverage dip" },
    [PSCustomObject]@{ zone_id = "Z07"; center_lat = 12.9397; center_lon = 77.6101; radius_m = 480; zone_type = "outskirts_weak_patch"; severity = "high"; attenuation_factor = 0.38; reason = "South-east fringe handover gap" },
    [PSCustomObject]@{ zone_id = "Z08"; center_lat = 12.9870; center_lon = 77.6369; radius_m = 340; zone_type = "underpass"; severity = "medium"; attenuation_factor = 0.55; reason = "Flyover shadowing" },
    [PSCustomObject]@{ zone_id = "Z09"; center_lat = 12.9712; center_lon = 77.5944; radius_m = 260; zone_type = "high_interference"; severity = "low"; attenuation_factor = 0.82; reason = "Core city interference pocket" },
    [PSCustomObject]@{ zone_id = "Z10"; center_lat = 12.9464; center_lon = 77.5518; radius_m = 440; zone_type = "sparse_area"; severity = "medium"; attenuation_factor = 0.64; reason = "Western corridor weak patch" }
)

$feedback = @(
    [PSCustomObject]@{ feedback_id = "F01"; lat = 12.9632; lon = 77.5712; issue_type = "signal_drop"; count = 4; last_seen = "2026-04-17"; weight_adjustment = -0.14 },
    [PSCustomObject]@{ feedback_id = "F02"; lat = 12.9904; lon = 77.6039; issue_type = "handover_issue"; count = 3; last_seen = "2026-04-17"; weight_adjustment = -0.10 },
    [PSCustomObject]@{ feedback_id = "F03"; lat = 12.9486; lon = 77.5842; issue_type = "blackout"; count = 5; last_seen = "2026-04-17"; weight_adjustment = -0.22 },
    [PSCustomObject]@{ feedback_id = "F04"; lat = 12.9792; lon = 77.5481; issue_type = "high_latency"; count = 2; last_seen = "2026-04-17"; weight_adjustment = -0.08 },
    [PSCustomObject]@{ feedback_id = "F05"; lat = 12.9549; lon = 77.6278; issue_type = "signal_drop"; count = 4; last_seen = "2026-04-17"; weight_adjustment = -0.12 },
    [PSCustomObject]@{ feedback_id = "F06"; lat = 12.9998; lon = 77.5675; issue_type = "handover_issue"; count = 2; last_seen = "2026-04-17"; weight_adjustment = -0.07 },
    [PSCustomObject]@{ feedback_id = "F07"; lat = 12.9397; lon = 77.6101; issue_type = "blackout"; count = 5; last_seen = "2026-04-17"; weight_adjustment = -0.24 },
    [PSCustomObject]@{ feedback_id = "F08"; lat = 12.9870; lon = 77.6369; issue_type = "signal_drop"; count = 3; last_seen = "2026-04-17"; weight_adjustment = -0.09 },
    [PSCustomObject]@{ feedback_id = "F09"; lat = 12.9712; lon = 77.5944; issue_type = "high_latency"; count = 2; last_seen = "2026-04-17"; weight_adjustment = -0.05 },
    [PSCustomObject]@{ feedback_id = "F10"; lat = 12.9464; lon = 77.5518; issue_type = "handover_issue"; count = 4; last_seen = "2026-04-17"; weight_adjustment = -0.11 },
    [PSCustomObject]@{ feedback_id = "F11"; lat = 12.9844; lon = 77.5835; issue_type = "signal_drop"; count = 2; last_seen = "2026-04-17"; weight_adjustment = -0.06 },
    [PSCustomObject]@{ feedback_id = "F12"; lat = 12.9588; lon = 77.6022; issue_type = "high_latency"; count = 3; last_seen = "2026-04-17"; weight_adjustment = -0.10 },
    [PSCustomObject]@{ feedback_id = "F13"; lat = 12.9748; lon = 77.6210; issue_type = "signal_drop"; count = 3; last_seen = "2026-04-17"; weight_adjustment = -0.08 },
    [PSCustomObject]@{ feedback_id = "F14"; lat = 12.9522; lon = 77.5663; issue_type = "blackout"; count = 4; last_seen = "2026-04-17"; weight_adjustment = -0.18 },
    [PSCustomObject]@{ feedback_id = "F15"; lat = 12.9921; lon = 77.5556; issue_type = "handover_issue"; count = 2; last_seen = "2026-04-17"; weight_adjustment = -0.06 }
)

$environmentProfiles = @(
    [PSCustomObject]@{ environment_type = "normal"; signal_multiplier = 1.00 },
    [PSCustomObject]@{ environment_type = "rain"; signal_multiplier = 0.85 },
    [PSCustomObject]@{ environment_type = "heavy_rain"; signal_multiplier = 0.70 },
    [PSCustomObject]@{ environment_type = "urban_dense"; signal_multiplier = 1.05 },
    [PSCustomObject]@{ environment_type = "tunnel"; signal_multiplier = 0.20 },
    [PSCustomObject]@{ environment_type = "underpass"; signal_multiplier = 0.50 }
)

$connectivityRows = New-Object System.Collections.Generic.List[object]

foreach ($segment in $roadSegments) {
    $providerSignals = @{}
    foreach ($provider in $providers) {
        $providerSignals[$provider] = 0.0
    }

    $totalSignal = 0.0
    $activeTowerCount = 0

    foreach ($tower in $towers) {
        $distance = Get-DistanceMeters -Lat1 $segment.midpoint_lat -Lon1 $segment.midpoint_lon -Lat2 $tower.lat -Lon2 $tower.lon
        if ($distance -le $tower.coverage_radius_m) {
            $signal = $tower.base_strength * (1.0 - ($distance / $tower.coverage_radius_m))
            if ($signal -gt $providerSignals[$tower.provider]) {
                $providerSignals[$tower.provider] = $signal
            }
            $totalSignal += $signal
            $activeTowerCount++
        }
    }

    $bestSignal = [double]($providerSignals.Values | Measure-Object -Maximum).Maximum
    $sortedSignals = $providerSignals.Values | Sort-Object -Descending
    $secondSignal = if ($sortedSignals.Count -ge 2) { [double]$sortedSignals[1] } else { 0.0 }
    $avgSignal = if ($activeTowerCount -gt 0) { $totalSignal / $activeTowerCount } else { 0.0 }
    $minSignal = if ($activeTowerCount -gt 0) { [Math]::Max(0.0, [Math]::Min($avgSignal, $bestSignal * 0.7)) } else { 0.0 }

    $attenuation = 1.0
    $deadZoneFlag = 0
    $zonePenalty = 0.0
    foreach ($zone in $weakZones) {
        $zoneDistance = Get-DistanceMeters -Lat1 $segment.midpoint_lat -Lon1 $segment.midpoint_lon -Lat2 $zone.center_lat -Lon2 $zone.center_lon
        if ($zoneDistance -le $zone.radius_m) {
            $attenuation *= $zone.attenuation_factor
            $zonePenalty += (1.0 - $zone.attenuation_factor)
            if ($zone.attenuation_factor -le 0.35) {
                $deadZoneFlag = 1
            }
        }
    }

    $feedbackPenalty = 0.0
    foreach ($entry in $feedback) {
        $feedbackDistance = Get-DistanceMeters -Lat1 $segment.midpoint_lat -Lon1 $segment.midpoint_lon -Lat2 $entry.lat -Lon2 $entry.lon
        if ($feedbackDistance -le 280.0) {
            $feedbackPenalty += [Math]::Abs($entry.weight_adjustment) * [Math]::Min(1.0, ($entry.count / 5.0))
        }
    }

    $avgSignal = Clamp -Value ($avgSignal * $attenuation * (1.0 - [Math]::Min($feedbackPenalty, 0.35))) -Min 0.0 -Max 100.0
    $bestSignal = Clamp -Value ($bestSignal * $attenuation * (1.0 - [Math]::Min($feedbackPenalty, 0.30))) -Min 0.0 -Max 100.0
    $minSignal = Clamp -Value ($minSignal * $attenuation * (1.0 - [Math]::Min($feedbackPenalty, 0.40))) -Min 0.0 -Max 100.0

    $providerRedundancyScore = Clamp -Value ($bestSignal + ($secondSignal * 0.75)) -Min 0.0 -Max 160.0
    $latencyRisk = Clamp -Value (1.0 - ($avgSignal / 100.0)) -Min 0.0 -Max 1.0
    $strongProviderCount = @($providerSignals.Values | Where-Object { $_ -ge 25.0 }).Count
    $handoverRisk = Clamp -Value ((4.0 - $strongProviderCount) * 0.08 + ($feedbackPenalty * 0.25) + ($zonePenalty * 0.08)) -Min 0.05 -Max 0.95
    $riskScore = Clamp -Value (($latencyRisk * 0.45) + (($deadZoneFlag * 0.30)) + ($feedbackPenalty * 0.20) + ($zonePenalty * 0.10) + ($handoverRisk * 0.15)) -Min 0.0 -Max 1.0
    $safeFlag = if (($minSignal -ge 50.0) -and ($deadZoneFlag -eq 0) -and ($riskScore -lt 0.4)) { 1 } else { 0 }

    $connectivityRows.Add([PSCustomObject]@{
        segment_id = $segment.segment_id
        avg_signal = [Math]::Round($avgSignal, 2)
        min_signal = [Math]::Round($minSignal, 2)
        provider_best_signal = [Math]::Round($bestSignal, 2)
        provider_redundancy_score = [Math]::Round($providerRedundancyScore, 2)
        dead_zone_flag = $deadZoneFlag
        risk_score = [Math]::Round($riskScore, 3)
        handover_risk = [Math]::Round($handoverRisk, 3)
        safe_flag = $safeFlag
    })
}

$roadSegments | Export-Csv -LiteralPath (Join-Path $rawDir "road_segments.csv") -NoTypeInformation
$towers | Export-Csv -LiteralPath (Join-Path $rawDir "towers.csv") -NoTypeInformation
$weakZones | Export-Csv -LiteralPath (Join-Path $rawDir "weak_zones.csv") -NoTypeInformation
$feedback | Export-Csv -LiteralPath (Join-Path $rawDir "feedback.csv") -NoTypeInformation
$environmentProfiles | Export-Csv -LiteralPath (Join-Path $rawDir "environment_profiles.csv") -NoTypeInformation
$connectivityRows | Export-Csv -LiteralPath (Join-Path $processedDir "segment_connectivity.csv") -NoTypeInformation

$summary = [PSCustomObject]@{
    city = "Bangalore"
    generated_on = (Get-Date -Format "yyyy-MM-dd")
    road_segments = $roadSegments.Count
    towers = $towers.Count
    weak_zones = $weakZones.Count
    feedback_entries = $feedback.Count
    connectivity_rows = $connectivityRows.Count
    center_lat = $cityCenterLat
    center_lon = $cityCenterLon
}

$summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $processedDir "adaptive_signal_map.json")
Write-Output "Generated Bangalore dataset in $OutputRoot"
