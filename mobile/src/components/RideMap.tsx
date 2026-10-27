import { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { useLanguage } from '@/lib/i18n';

import {
  MapOverlays,
  buildMapState,
  mapBoxStyle,
  onMapMessage,
  type RideMapProps,
} from './map/mapShared';
import { mapHtml, updateScript } from './map/mapPage';

export function RideMap(props: RideMapProps) {
  const web = useRef<WebView>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useLanguage();

  const [html] = useState(() =>
    mapHtml({
      center: {
        lat: props.initialCenter.lat,
        lng: props.initialCenter.lng,
      },
    }),
  );

  const script = updateScript(buildMapState(props));

  useEffect(() => {
    if (ready) web.current?.injectJavaScript(script);
  }, [ready, script]);

  return (
    <View style={mapBoxStyle(props.bottomInset, !!props.onCenterChange)}>
      <WebView
        ref={web}
        source={{ html, baseUrl: 'https://ride.app/' }}
        originWhitelist={['*']}
        onMessage={(e) => {
          const next = onMapMessage(e.nativeEvent.data, props, setReady);

          if (next === null) {
            setError(null);
          } else if (next !== undefined) {
            if (next.startsWith('Map tiles failed')) {
              setError(t('mapTilesError'));
            } else if (next.startsWith('Map failed to start')) {
              setError(t('mapStartError'));
            } else {
              setError(t('mapLoadError'));
            }
          }
        }}
        onError={() => setError(t('mapLoadError'))}
        style={StyleSheet.absoluteFill}
        scrollEnabled={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
      />
      <MapOverlays
        picking={!!props.onCenterChange}
        pinLabel={props.pinLabel}
        error={error}
      />
    </View>
  );
}
