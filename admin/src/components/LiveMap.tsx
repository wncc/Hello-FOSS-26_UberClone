import { useEffect, useRef } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import { latLngBounds, type LatLngExpression } from "leaflet";
import type { AdminMapData } from "../lib/api";

interface LiveMapProps {
  data: AdminMapData;
  fitRequest: number;
}

function FitMapToData({ data, fitRequest }: LiveMapProps) {
  const map = useMap();
  const hasInitialFit = useRef(false);
  const lastFitRequest = useRef(fitRequest);

  useEffect(() => {
    const points: LatLngExpression[] = [
      ...data.drivers.map(
        (driver) => [driver.lat, driver.lng] as LatLngExpression,
      ),
      ...data.rides.flatMap((ride) => [
        [ride.pickup.lat, ride.pickup.lng] as LatLngExpression,
        [ride.drop.lat, ride.drop.lng] as LatLngExpression,
      ]),
    ];

    if (points.length === 0) return;

    const requestedFit = fitRequest !== lastFitRequest.current;

    if (hasInitialFit.current && !requestedFit) return;

    if (points.length === 1) {
      map.setView(points[0], 14);
    } else {
      map.fitBounds(latLngBounds(points), {
        padding: [35, 35],
        maxZoom: 14,
      });
    }

    hasInitialFit.current = true;
    lastFitRequest.current = fitRequest;
  }, [data, fitRequest, map]);

  return null;
}

export default function LiveMap({ data, fitRequest }: LiveMapProps) {
  return (
    <div className="live-map">
      <MapContainer
        center={[19.076, 72.8777]}
        zoom={12}
        scrollWheelZoom
        className="live-map-canvas"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <FitMapToData data={data} fitRequest={fitRequest} />

        {data.drivers.map((driver) => (
          <CircleMarker
            key={driver.user_id}
            center={[driver.lat, driver.lng]}
            radius={8}
            pathOptions={{
              color: "#15803d",
              fillColor: "#22c55e",
              fillOpacity: 0.9,
            }}
          >
            <Popup>
              <strong>Online driver</strong>
              <br />
              Vehicle: {driver.vehicle_type}
              <br />
              Number: {driver.vehicle_number}
              <br />
              ID: {driver.user_id}
            </Popup>
          </CircleMarker>
        ))}

        {data.rides.map((ride) => (
          <Polyline
            key={ride.id}
            positions={[
              [ride.pickup.lat, ride.pickup.lng],
              [ride.drop.lat, ride.drop.lng],
            ]}
            pathOptions={{ color: "#2563eb", weight: 3, opacity: 0.75 }}
          >
            <Popup>
              <strong>Ride: {ride.id.slice(0, 12)}</strong>
              <br />
              Status: {ride.status.replaceAll("_", " ")}
              <br />
              Vehicle: {ride.vehicle_type}
            </Popup>
          </Polyline>
        ))}

        {data.rides.map((ride) => (
          <CircleMarker
            key={`${ride.id}-pickup`}
            center={[ride.pickup.lat, ride.pickup.lng]}
            radius={6}
            pathOptions={{
              color: "#1d4ed8",
              fillColor: "#60a5fa",
              fillOpacity: 1,
            }}
          >
            <Popup>Pickup · Ride {ride.id.slice(0, 12)}</Popup>
          </CircleMarker>
        ))}

        {data.rides.map((ride) => (
          <CircleMarker
            key={`${ride.id}-drop`}
            center={[ride.drop.lat, ride.drop.lng]}
            radius={6}
            pathOptions={{
              color: "#c2410c",
              fillColor: "#fb923c",
              fillOpacity: 1,
            }}
          >
            <Popup>Drop-off · Ride {ride.id.slice(0, 12)}</Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
