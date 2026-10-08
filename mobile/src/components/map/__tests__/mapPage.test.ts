/**
 * @jest-environment jsdom
 *
 * Runs the WebView map script against the real Leaflet library in jsdom.
 */
import { beforeEach, describe, expect, test } from '@jest/globals';

import { MAP_SCRIPT, mapHtml, parseMapMessage, updateScript, type MapState } from '../mapPage';

type Posted = { type: string; lat?: number; lng?: number; message?: string };

// jsdom has no layout; give the map a real size so Leaflet can compute views.
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 400 });
Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 600 });

// jsdom has no SVG geometry; Leaflet only needs this to exist to pick its SVG renderer (real WebViews have it).
(window.SVGSVGElement.prototype as unknown as { createSVGRect: () => object }).createSVGRect = () => ({});

// eslint-disable-next-line @typescript-eslint/no-require-imports
const L = require('leaflet');
const createRideMap = new Function(`${MAP_SCRIPT}; return createRideMap;`)() as (
  l: unknown, el: HTMLElement, post: (m: Posted) => void, opts: object,
) => { update: (s: MapState) => void; map: { getCenter(): { lat: number; lng: number }; getZoom(): number; eachLayer(f: (l: unknown) => void): void } };

const BLR = { lat: 12.9716, lng: 77.5946 };
const base: MapState = { picking: false, route: null, approach: null, pickup: null, drop: null, driver: null, me: null, recenter: null, fitKey: '' };

let posted: Posted[];
let ride: ReturnType<typeof createRideMap>;

function vectorLayers(): number {
  let n = 0;
  ride.map.eachLayer((l) => {
    if (l instanceof L.CircleMarker || l instanceof L.Polyline || (l instanceof L.Marker)) n += 1;
  });
  return n;
}

beforeEach(() => {
  document.body.innerHTML = '<div id="map"></div>';
  posted = [];
  ride = createRideMap(L, document.getElementById('map')!, (m) => posted.push(m),
    { center: BLR, zoom: 15, tileUrl: 'https://tiles.test/{z}/{x}/{y}.png', attribution: 'test' });
});

describe('map script', () => {
  test('starts at the given centre', () => {
    const c = ride.map.getCenter();
    expect(c.lat).toBeCloseTo(BLR.lat, 4);
    expect(c.lng).toBeCloseTo(BLR.lng, 4);
  });

  test('picking mode reports the centre after a recenter', () => {
    ride.update({ ...base, picking: true, recenter: { lat: 12.95, lng: 77.6, key: 'a#1' } });
    const last = posted.filter((m) => m.type === 'center').pop();
    expect(last?.lat).toBeCloseTo(12.95, 4);
    expect(last?.lng).toBeCloseTo(77.6, 4);
  });

  test('display mode does not report centre moves', () => {
    ride.update({ ...base, recenter: { lat: 12.95, lng: 77.6, key: 'a#1' } });
    expect(posted.filter((m) => m.type === 'center')).toHaveLength(0);
  });

  test('same recenter key does not move the map again', () => {
    ride.update({ ...base, picking: true, recenter: { lat: 12.95, lng: 77.6, key: 'a#1' } });
    ride.map.getCenter();
    const before = posted.length;
    ride.update({ ...base, picking: true, recenter: { lat: 12.95, lng: 77.6, key: 'a#1' } });
    expect(posted.length).toBe(before);
  });

  test('markers and route line are added, moved and removed', () => {
    const pickup = { lat: 12.9716, lng: 77.5946 };
    const drop = { lat: 12.9352, lng: 77.6245 };
    ride.update({ ...base, pickup, drop, driver: { lat: 12.97, lng: 77.59 }, fitKey: 'k1' });
    expect(vectorLayers()).toBe(4);                       // pickup, drop, driver, line
    const c = ride.map.getCenter();                        // fitted between the points
    expect(c.lat).toBeGreaterThan(12.93);
    expect(c.lat).toBeLessThan(12.98);
    ride.update({ ...base, pickup, fitKey: 'k2' });
    expect(vectorLayers()).toBe(1);
  });

  test('draws the road route instead of a straight line, and fits it in view', () => {
    const pickup = { lat: 19.0178, lng: 72.8478 };
    const drop = { lat: 19.0607, lng: 72.8636 };
    ride.update({ ...base, pickup, drop, fitKey: 'k1' });
    const polylines = () => {
      const found: { getLatLngs(): unknown[]; options: { dashArray?: string } }[] = [];
      ride.map.eachLayer((l) => { if (l instanceof L.Polyline && !(l instanceof L.Polygon)) found.push(l as never); });
      return found;
    };
    expect(polylines().map((l) => l.getLatLngs().length)).toEqual([2]);     // placeholder until the route arrives
    const route: [number, number][] = [[19.0178, 72.8478], [19.03, 72.84], [19.05, 72.845], [19.0607, 72.8636]];
    ride.update({ ...base, pickup, drop, route, fitKey: 'k2' });
    expect(polylines().map((l) => l.getLatLngs().length)).toEqual([4]);     // only the road route
    const c = ride.map.getCenter();
    expect(c.lng).toBeLessThan(72.86);                                       // pulled west by the route's bend

    ride.update({ ...base, pickup, drop, route, approach: [[19.0, 72.83], [19.0178, 72.8478]], fitKey: 'k3' });
    expect(polylines()).toHaveLength(2);
  });

  test('unchanged paths are not redrawn on driver updates', () => {
    const route: [number, number][] = [[19.0, 72.8], [19.01, 72.81], [19.02, 72.82]];
    ride.update({ ...base, route, fitKey: 'k1' });
    let first: unknown = null;
    ride.map.eachLayer((l) => { if (l instanceof L.Polyline) first = l; });
    ride.update({ ...base, route: route.map((p) => [...p] as [number, number]), driver: { lat: 19.005, lng: 72.805 }, fitKey: 'k1' });
    let second: unknown = null;
    ride.map.eachLayer((l) => { if (l instanceof L.Polyline) second = l; });
    expect(second).toBe(first);
  });

  test('tile failures are reported once', () => {
    ride.map.eachLayer((l) => {
      if (l instanceof L.TileLayer) {
        (l as { fire(e: string): void }).fire('tileerror');
        (l as { fire(e: string): void }).fire('tileerror');
      }
    });
    expect(posted.filter((m) => m.type === 'error')).toEqual([{ type: 'error', message: 'Map tiles failed to load' }]);
  });
});

describe('bridge helpers', () => {
  test('html embeds the script, leaflet and options', () => {
    const html = mapHtml({ center: BLR });
    expect(html).toContain('function createRideMap');
    expect(html).toContain('leaflet@1.9.4/dist/leaflet.js');
    expect(html).toContain('"lat":12.9716');
  });

  test('update script is valid JS calling update', () => {
    const calls: MapState[] = [];
    const win = { rideMap: { update: (s: MapState) => calls.push(s) } };
    const state = { ...base, pickup: { lat: 1, lng: 2 }, fitKey: "it's \"quoted\"" };
    new Function('window', updateScript(state))(win);
    expect(calls).toEqual([state]);
  });

  test('parses only well-formed messages', () => {
    expect(parseMapMessage('{"type":"ready"}')).toEqual({ type: 'ready' });
    expect(parseMapMessage('{"type":"center","lat":1,"lng":2}')).toEqual({ type: 'center', lat: 1, lng: 2 });
    expect(parseMapMessage('{"type":"center","lat":"x"}')).toBeNull();
    expect(parseMapMessage('not json')).toBeNull();
  });
});
