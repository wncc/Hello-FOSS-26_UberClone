import { createClient } from 'redis';

const EXTERNAL_API = process.env.EXTERNAL_API || 'http://localhost:4000';
const TICK_MS = 3000;
const RADIUS_KM = 4;              // 3–5 km ping radius
const RESERVE_RATIO = 0.2;        // keep 20% of free drivers unpinged this round
const MAX_DRIVERS_PER_RIDER = 3;  // broadcast fan-out cap per rider
const GEO_KEY = 'geo:drivers:free';

const redis = createClient({ url: "process.env.REDIS_URL"}); // ADD .ENV FILE WITH REDIS URL
redis.on('error', (err) => console.error('Redis error:', err));
await redis.connect();
// connected to redis


// distance formula
function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}


// shuffle an array
function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}


// fetching and pushing data functions
async function fetchState() {
  const res = await fetch(`${EXTERNAL_API}/state`);
  if (!res.ok) throw new Error(`fetch /state failed: ${res.status}`);
  return res.json();
}

async function pushState(drivers, riders) {
  const res = await fetch(`${EXTERNAL_API}/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ drivers, riders }),
  });
  if (!res.ok) throw new Error(`post /update failed: ${res.status}`);
}




// resolve rides where >1 driver accepted the same rider 
// Nearest driver wins; the rest are freed up for the next round.
function resolveAcceptedConflicts(driverById, riderById) {
  const acceptedByRider = new Map();

  for (const d of driverById.values()) {
    if (d.status === 'accepted' && d.riderId) {
      if (!acceptedByRider.has(d.riderId)) acceptedByRider.set(d.riderId, []);
      acceptedByRider.get(d.riderId).push(d);
    }
  }

  for (const [riderId, candidates] of acceptedByRider) {
    const rider = riderById.get(riderId);
    if (!rider) continue;

    let winner = candidates[0];
    let bestDist = haversineKm(rider, winner);
    for (const d of candidates.slice(1)) {
      const dist = haversineKm(rider, d);
      if (dist < bestDist) {
        bestDist = dist;
        winner = d;
      }
    }

    for (const d of candidates) {
      if (d.id !== winner.id) {
        d.status = 'free';
        d.riderId = null;
      }
    }

    rider.status = 'accepted';
    rider.driverId = winner.id;
    rider.driverIds = [];
  }
}

// assign new pings to free drivers / pending riders 
async function assignPings(drivers, driverById, riders) {
  const freeDrivers = drivers.filter((d) => d.status === 'free');

  await redis.del(GEO_KEY);
  if (freeDrivers.length) {
    await redis.geoAdd(
      GEO_KEY,
      freeDrivers.map((d) => ({ longitude: d.lng, latitude: d.lat, member: d.id }))
    );
  }

  // Reserve a slice of free drivers for future rounds (not pinged this cycle).
  const shuffledFree = shuffle(freeDrivers);
  const reserveCount = Math.floor(shuffledFree.length * RESERVE_RATIO);
  const usableIds = new Set(
    shuffledFree.slice(0, shuffledFree.length - reserveCount).map((d) => d.id)
  );

  const pendingRiders = shuffle(riders.filter((r) => r.status === 'ping_pending'));

  for (const rider of pendingRiders) {
    if (usableIds.size === 0) break;

    const nearbyIds = await redis.geoSearch(
      GEO_KEY,
      { longitude: rider.lng, latitude: rider.lat },
      { radius: RADIUS_KM, unit: 'km' }
    );

    const eligible = nearbyIds.filter((id) => usableIds.has(id));
    if (!eligible.length) continue;

    // Uniform random pick among eligible free drivers (not nearest-first).
    const chosen = shuffle(eligible).slice(0, Math.min(MAX_DRIVERS_PER_RIDER, eligible.length));

    for (const driverId of chosen) {
      const driver = driverById.get(driverId);
      driver.status = 'pinged';
      driver.riderId = rider.id;
      usableIds.delete(driverId);
    }

    rider.status = 'driver_pinged';
    rider.driverIds = chosen;
  }
}

//  Main cycle
async function runCycle() {
  const { drivers, riders } = await fetchState();

  const driverById = new Map(drivers.map((d) => [d.id, d]));
  const riderById = new Map(riders.map((r) => [r.id, r]));

  resolveAcceptedConflicts(driverById, riderById);
  await assignPings(drivers, driverById, riders);
  await pushState(drivers, riders);

  const accepted = riders
    .filter((r) => r.status === 'accepted')
    .map((r) => ({ riderId: r.id, driverId: r.driverId }));

  console.log(
    `[cycle] accepted=${accepted.length} pinged_riders=${riders.filter((r) => r.status === 'driver_pinged').length} free_drivers=${drivers.filter((d) => d.status === 'free').length}`
  );

  return { accepted, drivers, riders };
}

let running = false;

setInterval(async () => {
    if (running) return;

    running = true;

    try {
        await runCycle();
    } catch (err) {
        console.error("Cycle error:", err.message);
    } finally {
        running = false;
    }
}, TICK_MS);

runCycle().catch((err) => console.error('Cycle error:', err.message));
