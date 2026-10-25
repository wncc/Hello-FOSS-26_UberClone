# GPS-Based Signal and Turn Delay Learning

## Overview

This module estimates traffic-signal waits and turn delays using GPS observations from driver trips.

It replaces fixed delay assumptions with learned estimates when sufficient evidence is available. Otherwise, the router continues using its existing defaults.

## How It Works

1. GPS observations are matched to road segments.
2. Each pass through a junction is found, and the time the vehicle was stopped just
   before or at it is measured. Passes without a stop are recorded as 0 s waits.
3. Direction comes from the road network: the entering road must end at the junction
   and the leaving road must start there. Signals use the mapped `traffic_signals`
   feature; other junctions are turn movements.
4. Observations are grouped by junction, turn movement, and local time bucket.
5. Repeated observations from the same driver are limited.
6. Estimates are calculated using recent observations and shrinkage toward default delays.
7. Learned delays are used in local routing and ETA calculations.

## Time Buckets

The system uses 72 time-of-week buckets:

- 24 weekday hourly buckets.
- 24 Saturday hourly buckets.
- 24 Sunday hourly buckets.

Local timestamps determine the applicable bucket.

## Evidence and Fallback

The default learning policy uses:

| Parameter                | Value       |
| ------------------------ | ----------- |
| Observation window       | 56 days     |
| Recency half-life        | 28 days     |
| Minimum distinct drivers | 5           |
| Minimum distinct days    | 3           |
| Minimum effective weight | 10          |
| Prior weight             | 5           |
| Maximum accepted wait    | 600 seconds (longer stops are dropped, not clipped) |

Observations are limited to one vote per driver per hour for each learned movement.

When evidence is insufficient, the system uses the existing signal or turn-cost default.

## Routing Integration

The local A\* router can use learned waits when evaluating road segments and turns.

Elapsed travel time is tracked separately from weighted routing cost to select the appropriate time bucket at each junction.

The route ETA calculation also accounts for signal and turn delays.

When speed samples are turned into road-speed evidence, the same wait that routing adds (learned at signals, mapped elsewhere) is removed from the sample. Refresh delays before refreshing telemetry so both use the same model.

## GPS Extraction Limitations

- Stationary GPS points near a junction do not always prove that a traffic signal or turn caused the stop. Parking, pickup activity, congestion, and GPS errors may produce similar observations.
- The current extraction logic has been tested using synthetic GPS trips. Real-world validation remains necessary.
- GPS map matching currently uses nearest-segment searches and is not yet optimized with a spatial index for large road networks.
- Waits are measured within 50 m of the junction. Longer queues are under-measured, so errors are low, not high.
- Turn values measure stopped time only, not slowing down for the turn. They shrink toward the default turn cost, which includes turning time.
- Zero-wait crossings are stored for signals and for junctions with a real choice of exits, so a trip can produce many rows.
- Ping times are the server's receive time. Offline buffering can distort gaps.

## Backend Integration

The routing service supports explicit refreshes from GPS trips through `refresh_delays_from_gps()`.

Automatic ingestion of completed rides, database persistence of delay observations, and periodic model refresh are not yet connected on this branch.

The earlier GPS road-learning implementation on `feat/gps-road-learning` provides reusable ride-loading and background-processing components. Integration should be coordinated with that work to avoid duplicate implementations.

## Additional Limitations

- GraphHopper-backed route selection does not currently optimize using learned delays.
- The time-dependent local router has not been proven globally optimal across every bucket transition.
- Learning models must be refreshed with the intended observation window.
- Real-world accuracy and city-scale performance have not yet been benchmarked.

## Verification

The test suite covers synthetic signal and turn observations, evidence thresholds, sparse-data fallback, driver vote limits, routing integration, and arrival-time bucket selection.

Passing unit tests does not establish production readiness.
