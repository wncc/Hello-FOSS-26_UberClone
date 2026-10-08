/**
 * The web page shown inside the map WebView: Leaflet + OpenStreetMap-style raster tiles.
 *
 * Why not react-native-maps: in Expo Go SDK 57 on Android it never loads Google tiles
 * (https://github.com/expo/expo/issues/49323). Leaflet in a WebView works in Expo Go on
 * every platform and needs no API key.
 *
 * MAP_SCRIPT is plain ES5 so it runs in any WebView, and it is unit-tested with the real
 * Leaflet library in jsdom (see __tests__/mapPage.test.ts).
 */

export const LEAFLET_VERSION = '1.9.4';

/**
 * Tile server. The default OpenStreetMap server is fine for development and testing; its usage
 * policy does not allow app traffic at scale, so set EXPO_PUBLIC_MAP_TILE_URL to a hosted provider
 * (MapTiler, Stadia, Ola Maps, ...) before launch.
 */
export const TILE_URL = process.env.EXPO_PUBLIC_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const TILE_ATTRIBUTION = process.env.EXPO_PUBLIC_MAP_ATTRIBUTION || '© OpenStreetMap contributors';

/** Defines createRideMap(L, element, post, options) -> { update(state) }. */
export const MAP_SCRIPT = String.raw`
function createRideMap(L, el, post, opts) {
  var map = L.map(el, { zoomControl: false, attributionControl: true })
    .setView([opts.center.lat, opts.center.lng], opts.zoom || 15);
  var tileErrorSent = false;
  L.tileLayer(opts.tileUrl, { maxZoom: 19, attribution: opts.attribution })
    .on('tileerror', function () {
      if (!tileErrorSent) { tileErrorSent = true; post({ type: 'error', message: 'Map tiles failed to load' }); }
    })
    .addTo(map);

  var layers = { pickup: null, drop: null, driver: null, me: null, line: null, route: null, approach: null };
  var lineKeys = {};
  var picking = false, lastRecenter = null, lastFit = null;

  function dot(color, radius) {
    return function (ll) {
      return L.circleMarker(ll, { radius: radius, color: '#ffffff', weight: 3, fillColor: color, fillOpacity: 1 });
    };
  }
  function vehicle(ll) {
    return L.marker(ll, { icon: L.divIcon({ html: '<div style="font-size:28px;line-height:28px">🚘</div>',
                                             className: '', iconSize: [28, 28], iconAnchor: [14, 14] }) });
  }
  var makers = { pickup: dot('#16a34a', 9), drop: dot('#dc2626', 9), driver: vehicle, me: dot('#2563eb', 7) };

  function setPoint(name, p) {
    if (!p) {
      if (layers[name]) { map.removeLayer(layers[name]); layers[name] = null; }
      return;
    }
    if (layers[name]) layers[name].setLatLng([p.lat, p.lng]);
    else layers[name] = makers[name]([p.lat, p.lng]).addTo(map);
  }

  function pathKey(pts) {
    return pts && pts.length > 1 ? pts.length + ':' + pts[0] + ':' + pts[pts.length - 1] : '';
  }
  // Redraws a polyline only when its points changed (driver location updates arrive every few seconds).
  function setLine(name, pts, style) {
    var key = pathKey(pts);
    if (lineKeys[name] === key) return;
    lineKeys[name] = key;
    if (layers[name]) { map.removeLayer(layers[name]); layers[name] = null; }
    if (key) layers[name] = L.polyline(pts, style).addTo(map);
  }

  // The map's box changes size (e.g. picking mode -> route display); Leaflet must re-measure.
  window.addEventListener('resize', function () { map.invalidateSize(); });

  map.on('moveend', function () {
    if (!picking) return;
    var c = map.getCenter();
    post({ type: 'center', lat: c.lat, lng: c.lng });
  });

  function update(s) {
    map.invalidateSize();
    picking = !!s.picking;
    setPoint('pickup', s.pickup);
    setPoint('drop', s.drop);
    setPoint('driver', s.driver);
    setPoint('me', s.me);

    var hasRoute = !!(s.route && s.route.length > 1);
    // The road route; a dashed straight line only as a fallback while no route is known.
    setLine('route', hasRoute ? s.route : null, { color: '#111827', weight: 5, opacity: 0.85 });
    setLine('line', !hasRoute && s.pickup && s.drop ? [[s.pickup.lat, s.pickup.lng], [s.drop.lat, s.drop.lng]] : null,
            { color: '#6b7280', weight: 3, dashArray: '6 8' });
    setLine('approach', s.approach, { color: '#2563eb', weight: 5, opacity: 0.9, dashArray: '1 9', lineCap: 'round' });

    if (s.recenter && s.recenter.key !== lastRecenter) {
      lastRecenter = s.recenter.key;
      map.setView([s.recenter.lat, s.recenter.lng], Math.max(map.getZoom(), 15), { animate: false });
    } else if (!picking && s.fitKey !== lastFit) {
      lastFit = s.fitKey;
      var pts = [s.pickup, s.drop, s.driver].filter(Boolean).map(function (p) { return [p.lat, p.lng]; })
        .concat(hasRoute ? s.route : [], s.approach || []);
      // Keep everything clear of the bottom panel, which covers the lower part of the map.
      var bottom = (s.coveredBottom || 0) + 40;
      if (pts.length > 1) map.fitBounds(pts, { paddingTopLeft: [40, 90], paddingBottomRight: [40, bottom], maxZoom: 17 });
      else if (pts.length === 1) map.setView(pts[0], Math.max(map.getZoom(), 15));
    }
  }

  return { update: update, map: map };
}
`;

export interface MapOptions {
  center: { lat: number; lng: number };
  zoom?: number;
  tileUrl?: string;
  attribution?: string;
}

export function mapHtml(options: MapOptions): string {
  const opts = JSON.stringify({ tileUrl: TILE_URL, attribution: TILE_ATTRIBUTION, ...options });
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<link rel="stylesheet" href="https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css">
<style>html, body, #map { margin: 0; padding: 0; height: 100%; width: 100%; background: #e5e7eb; }</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js"></script>
<script>
${MAP_SCRIPT}
(function () {
  function post(m) {
    var s = JSON.stringify(m);
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(s);
    else window.parent.postMessage(s, '*');   // browser build: the map is an iframe
  }
  if (!window.L) { post({ type: 'error', message: 'Could not load the map (check the internet connection)' }); return; }
  try {
    window.rideMap = createRideMap(window.L, document.getElementById('map'), post, ${opts});
    post({ type: 'ready' });
  } catch (e) {
    post({ type: 'error', message: 'Map failed to start: ' + e.message });
  }
})();
</script>
</body>
</html>`;
}

export type Path = [number, number][];   // [lat, lng] points

/** What the native side sends on every change. */
export interface MapState {
  picking: boolean;
  route: Path | null;
  approach: Path | null;
  pickup: { lat: number; lng: number } | null;
  drop: { lat: number; lng: number } | null;
  driver: { lat: number; lng: number } | null;
  me: { lat: number; lng: number } | null;
  recenter: { lat: number; lng: number; key: string } | null;
  fitKey: string;
  /** Pixels at the bottom of the map hidden behind the panel (display mode). */
  coveredBottom?: number;
}

export type MapMessage =
  | { type: 'ready' }
  | { type: 'center'; lat: number; lng: number }
  | { type: 'error'; message: string };

export function parseMapMessage(raw: string): MapMessage | null {
  try {
    const m = JSON.parse(raw);
    if (m?.type === 'ready') return m;
    if (m?.type === 'center' && Number.isFinite(m.lat) && Number.isFinite(m.lng)) return m;
    if (m?.type === 'error' && typeof m.message === 'string') return m;
  } catch {
    // ignore non-JSON messages
  }
  return null;
}

/** JS to run in the page for a state update. JSON is a valid JS literal, so no escaping is needed. */
export function updateScript(state: MapState): string {
  return `window.rideMap && window.rideMap.update(${JSON.stringify(state)}); true;`;
}
