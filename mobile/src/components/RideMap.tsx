import { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';

import type { LatLng } from '@/lib/types';

import { mapHtml, parseMapMessage, updateScript, type MapState, type Path } from './map/mapPage';
import { colors } from './ui';

const key = (p: LatLng | null | undefined) => (p ? `${p.lat.toFixed(5)},${p.lng.toFixed(5)}` : '');
const point = (p: LatLng | null | undefined) => (p ? { lat: p.lat, lng: p.lng } : null);
const pathKey = (p: Path | null | undefined) => (p && p.length > 1 ? `${p.length}:${p[0]}:${p[p.length - 1]}` : '');
const SHEET_OVERLAP = 20;   // the map runs a little under the sheet's rounded corners

/**
 * Map area above the bottom sheet (Leaflet in a WebView).
 *  - Picking mode (`onCenterChange` set): a fixed centre pin; reports where the user dragged
 *    the map. `recenterTo` / `recenterKey` move the map programmatically.
 *  - Display mode: shows pickup / drop / driver markers and keeps them in view.
 * `me` draws the user's own position.
 */
export function RideMap({
  initialCenter, recenterTo, recenterKey = 0, pickup, drop, driver, me, route, approach, onCenterChange, pinLabel,
  bottomInset = 0,
}: {
  initialCenter: LatLng;
  recenterTo?: LatLng | null;
  recenterKey?: number;
  pickup?: LatLng | null;
  drop?: LatLng | null;
  driver?: LatLng | null;
  me?: LatLng | null;
  /** Road path pickup -> drop. Without it a dashed straight line is drawn as a placeholder. */
  route?: Path | null;
  /** Driver's road path to the pickup. */
  approach?: Path | null;
  onCenterChange?: (p: LatLng) => void;
  pinLabel?: string;
  bottomInset?: number;
}) {
  const web = useRef<WebView>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picking = !!onCenterChange;

  // The page is built once; later changes go through update() so the map isn't reloaded.
  const [html] = useState(() => mapHtml({ center: { lat: initialCenter.lat, lng: initialCenter.lng } }));

  const state: MapState = {
    picking,
    route: route && route.length > 1 ? route : null,
    approach: approach && approach.length > 1 ? approach : null,
    pickup: point(pickup),
    drop: point(drop),
    driver: point(driver),
    me: point(me),
    recenter: recenterTo ? { lat: recenterTo.lat, lng: recenterTo.lng, key: `${key(recenterTo)}#${recenterKey}` } : null,
    fitKey: [[pickup, drop, driver].map(key).join('|'), pathKey(route), pathKey(approach)].join('#'),
  };
  const script = updateScript(state);   // a string, so the effect below runs only when something changed

  useEffect(() => {
    if (ready) web.current?.injectJavaScript(script);
  }, [ready, script]);

  function onMessage(e: WebViewMessageEvent) {
    const msg = parseMapMessage(e.nativeEvent.data);
    if (!msg) return;
    if (msg.type === 'ready') {
      setError(null);
      setReady(true);
    } else if (msg.type === 'center') {
      onCenterChange?.({ lat: msg.lat, lng: msg.lng });
    } else {
      setError(msg.message);
    }
  }

  const box = { position: 'absolute' as const, top: 0, left: 0, right: 0, bottom: Math.max(0, bottomInset - SHEET_OVERLAP) };

  return (
    <View style={box}>
      <WebView
        ref={web}
        source={{ html, baseUrl: 'https://ride.app/' }}
        originWhitelist={['*']}
        onMessage={onMessage}
        onError={() => setError('Could not load the map')}
        style={StyleSheet.absoluteFill}
        scrollEnabled={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
      />
      {picking ? (
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <View style={styles.pinAnchor}>
            {pinLabel ? <Text style={styles.pinLabel}>{pinLabel}</Text> : null}
            <Text style={styles.pin}>📍</Text>
          </View>
        </View>
      ) : null}
      {error ? (
        <View pointerEvents="none" style={styles.errorWrap}>
          <Text style={styles.error}>{error}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  // The bottom of this block (the pin's tip) sits exactly on the map centre, which is what gets reported.
  pinAnchor: { position: 'absolute', left: 0, right: 0, bottom: '50%', alignItems: 'center' },
  pin: { fontSize: 36, lineHeight: 40, marginBottom: -4 },
  pinLabel: {
    backgroundColor: colors.primary, color: colors.primaryText, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 8, overflow: 'hidden', fontWeight: '600', marginBottom: 2,
  },
  errorWrap: { position: 'absolute', top: 100, left: 16, right: 16, alignItems: 'center' },
  error: {
    backgroundColor: colors.danger, color: colors.primaryText, padding: 10, borderRadius: 10, overflow: 'hidden',
    fontWeight: '600', textAlign: 'center',
  },
});
