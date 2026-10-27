import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { useLanguage } from '@/lib/i18n';

import {
  MapOverlays,
  buildMapState,
  mapBoxStyle,
  onMapMessage,
  type RideMapProps,
} from './map/mapShared';
import { mapHtml, type MapState } from './map/mapPage';

type MapWindow = Window & { rideMap?: { update(s: MapState): void } };

export function RideMap(props: RideMapProps) {
  const frame = useRef<HTMLIFrameElement>(null);
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

  const latestProps = useRef(props);

  useEffect(() => {
    latestProps.current = props;
  });

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.source !== frame.current?.contentWindow || typeof e.data !== 'string') return;

      const next = onMapMessage(e.data, latestProps.current, setReady);

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
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [t]);

  const state = JSON.stringify(buildMapState(props));

  useEffect(() => {
    if (ready) {
      (frame.current?.contentWindow as MapWindow | null)?.rideMap?.update(JSON.parse(state));
    }
  }, [ready, state]);

  return (
    <View style={mapBoxStyle(props.bottomInset, !!props.onCenterChange)}>
      <iframe
        ref={frame}
        srcDoc={html}
        title={t('appName')}
        style={{ border: 0, width: '100%', height: '100%' }}
      />
      <MapOverlays
        picking={!!props.onCenterChange}
        pinLabel={props.pinLabel}
        error={error}
      />
    </View>
  );
}
