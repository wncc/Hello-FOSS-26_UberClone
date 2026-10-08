import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { MapOverlays, buildMapState, mapBoxStyle, onMapMessage, type RideMapProps } from './map/mapShared';
import { mapHtml, type MapState } from './map/mapPage';

type MapWindow = Window & { rideMap?: { update(s: MapState): void } };

/** Browser version of RideMap: the same Leaflet page, in an iframe instead of a WebView. */
export function RideMap(props: RideMapProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [html] = useState(() => mapHtml({ center: { lat: props.initialCenter.lat, lng: props.initialCenter.lng } }));
  const latestProps = useRef(props);
  useEffect(() => {
    latestProps.current = props;
  });

  // The page posts to window.parent when it isn't inside a React Native WebView.
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.source !== frame.current?.contentWindow || typeof e.data !== 'string') return;
      const next = onMapMessage(e.data, latestProps.current, setReady);
      if (next !== undefined) setError(next);
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const state = JSON.stringify(buildMapState(props));
  useEffect(() => {
    if (ready) (frame.current?.contentWindow as MapWindow | null)?.rideMap?.update(JSON.parse(state));
  }, [ready, state]);

  return (
    <View style={mapBoxStyle(props.bottomInset, !!props.onCenterChange)}>
      <iframe ref={frame} srcDoc={html} title="map" style={{ border: 0, width: '100%', height: '100%' }} />
      <MapOverlays picking={!!props.onCenterChange} pinLabel={props.pinLabel} error={error} />
    </View>
  );
}
