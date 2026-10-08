/** Everything the native (WebView) and web (iframe) map share: props, state, overlays. */
import { StyleSheet, Text, View } from 'react-native';

import type { LatLng } from '@/lib/types';

import { colors } from '../ui';
import { parseMapMessage, type MapState, type Path } from './mapPage';

export interface RideMapProps {
  initialCenter: LatLng;
  recenterTo?: LatLng | null;
  /** Bump to recenter on the same point again (e.g. "use my location" after dragging away). */
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
}

const key = (p: LatLng | null | undefined) => (p ? `${p.lat.toFixed(5)},${p.lng.toFixed(5)}` : '');
const point = (p: LatLng | null | undefined) => (p ? { lat: p.lat, lng: p.lng } : null);
const pathKey = (p: Path | null | undefined) => (p && p.length > 1 ? `${p.length}:${p[0]}:${p[p.length - 1]}` : '');
const SHEET_OVERLAP = 20;   // the map runs a little under the sheet's rounded corners

export function buildMapState(p: RideMapProps): MapState {
  return {
    picking: !!p.onCenterChange,
    route: p.route && p.route.length > 1 ? p.route : null,
    approach: p.approach && p.approach.length > 1 ? p.approach : null,
    pickup: point(p.pickup),
    drop: point(p.drop),
    driver: point(p.driver),
    me: point(p.me),
    recenter: p.recenterTo
      ? { lat: p.recenterTo.lat, lng: p.recenterTo.lng, key: `${key(p.recenterTo)}#${p.recenterKey ?? 0}` }
      : null,
    fitKey: [[p.pickup, p.drop, p.driver].map(key).join('|'), pathKey(p.route), pathKey(p.approach)].join('#'),
    coveredBottom: p.onCenterChange ? 0 : p.bottomInset ?? 0,
  };
}

/** Handles a message from the map page; returns the new error text (or null to clear, undefined = unchanged). */
export function onMapMessage(raw: string, props: RideMapProps, setReady: (r: boolean) => void): string | null | undefined {
  const msg = parseMapMessage(raw);
  if (!msg) return undefined;
  if (msg.type === 'ready') {
    setReady(true);
    return null;
  }
  if (msg.type === 'center') {
    props.onCenterChange?.({ lat: msg.lat, lng: msg.lng });
    return undefined;
  }
  return msg.message;
}

/**
 * Picking mode: the map ends just under the panel, so the centre pin is the centre of what you see.
 * Display mode: the map fills the screen behind the panel (no empty band); fitting keeps
 * markers and routes clear of the covered part.
 */
export function mapBoxStyle(bottomInset = 0, picking = false) {
  return { position: 'absolute' as const, top: 0, left: 0, right: 0,
           bottom: picking ? Math.max(0, bottomInset - SHEET_OVERLAP) : 0 };
}

/** Centre pin (picking mode) and error banner, drawn over the map. */
export function MapOverlays({ picking, pinLabel, error }: { picking: boolean; pinLabel?: string; error: string | null }) {
  return (
    <>
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
    </>
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
