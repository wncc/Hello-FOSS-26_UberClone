import { useEffect, useRef, useState } from 'react';
import { StyleSheet, View, useColorScheme } from 'react-native';
import { WebView } from 'react-native-webview';

import { MAP_BG } from '@/lib/theme';

import { MapOverlays, buildMapState, mapBoxStyle, onMapMessage, type RideMapProps } from './map/mapShared';
import { darkScript, mapHtml, updateScript } from './map/mapPage';

/**
 * Map area above the bottom sheet: Leaflet in a WebView (RideMap.web.tsx is the browser version).
 *  - Picking mode (`onCenterChange` set): a fixed centre pin; reports where the user dragged
 *    the map. `recenterTo` / `recenterKey` move the map programmatically.
 *  - Display mode: shows pickup / drop / driver markers and keeps them in view.
 */
export function RideMap(props: RideMapProps) {
  const web = useRef<WebView>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dark = useColorScheme() === 'dark';

  // The page is built once; later changes go through update() / setDark() so the map isn't reloaded.
  const [html] = useState(() => mapHtml({ center: { lat: props.initialCenter.lat, lng: props.initialCenter.lng }, dark }));
  const script = updateScript(buildMapState(props));   // a string, so the effect runs only when something changed

  useEffect(() => {
    if (ready) web.current?.injectJavaScript(script);
  }, [ready, script]);

  useEffect(() => {
    if (ready) web.current?.injectJavaScript(darkScript(dark));
  }, [ready, dark]);

  const background = dark ? MAP_BG.dark : MAP_BG.light;   // no white flash before the page paints
  return (
    <View style={[mapBoxStyle(props.bottomInset, !!props.onCenterChange), { backgroundColor: background }]}>
      <WebView
        ref={web}
        source={{ html, baseUrl: 'https://ride.app/' }}
        originWhitelist={['*']}
        onMessage={(e) => {
          const next = onMapMessage(e.nativeEvent.data, props, setReady);
          if (next !== undefined) setError(next);
        }}
        onError={() => setError('Could not load the map')}
        style={[StyleSheet.absoluteFill, { backgroundColor: background }]}
        scrollEnabled={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
      />
      <MapOverlays picking={!!props.onCenterChange} pinLabel={props.pinLabel} error={error} />
    </View>
  );
}
