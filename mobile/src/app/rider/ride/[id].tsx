import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Loading, Row, Sheet, Title, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { VEHICLE_ICON, VEHICLE_LABEL, formatFare, isFinished, riderStatusText, shortAddress } from '@/lib/format';
import { confirmAction } from '@/lib/dialogs';
import { applyRiderEvent } from '@/lib/rideState';
import { useServerEvents, useSession } from '@/lib/session';
import { useRideRoute } from '@/lib/useRideRoute';
import type { Ride } from '@/lib/types';

const POLL_MS = 10_000;   // safety net if a live event is missed

export default function RiderRide() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useSession();
  const [ride, setRide] = useState<Ride | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const roads = useRideRoute(id, ride?.status);

  const load = useCallback(() => {
    api.ride(id).then(setRide).catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load the ride'));
  }, [api, id]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  useServerEvents((e) => {
    setRide((r) => (r ? applyRiderEvent(r, e) : r));
    if (e.event === 'ride:driver_assigned' || e.event === 'ride:completed') load();   // full details (driver, fare)
  });

  function cancel() {
    confirmAction('Cancel ride?', 'Your driver may already be on the way.', 'Cancel ride', async () => {
      setBusy(true);
      try {
        setRide(await api.cancel(id, 'cancelled by rider'));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Could not cancel');
      } finally {
        setBusy(false);
      }
    });
  }

  if (!ride) return error ? <View style={styles.center}><ErrorText message={error} /></View> : <Loading />;

  const driverPos = ride.driver?.lat != null && ride.driver?.lng != null ? { lat: ride.driver.lat, lng: ride.driver.lng } : null;
  const cancellable = ['searching', 'driver_assigned', 'driver_arrived'].includes(ride.status);

  return (
    <View style={{ flex: 1 }}>
      <RideMap initialCenter={ride.pickup} pickup={ride.pickup} drop={ride.drop} driver={driverPos} bottomInset={320}
               route={roads?.trip} approach={ride.status === 'driver_assigned' ? roads?.approach : null} />
      <Sheet>
        <Title style={{ fontSize: 20 }}>{riderStatusText(ride.status)}</Title>

        {ride.driver && !isFinished(ride.status) ? (
          <Row style={styles.driverRow}>
            <Text style={{ fontSize: 32 }}>{VEHICLE_ICON[ride.vehicle_type]}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.strong}>{ride.driver.name ?? 'Your driver'}{ride.driver.rating ? ` · ★ ${ride.driver.rating}` : ''}</Text>
              <Body muted>{ride.driver.vehicle_number}{ride.driver.vehicle_model ? ` · ${ride.driver.vehicle_model}` : ''}</Body>
            </View>
            {ride.pin && ride.status !== 'in_progress' ? (
              <View style={styles.pinBox}>
                <Text style={styles.pinLabel}>PIN</Text>
                <Text style={styles.pin}>{ride.pin}</Text>
              </View>
            ) : null}
          </Row>
        ) : null}

        {ride.status === 'searching' ? <Body muted>Pinging {VEHICLE_LABEL[ride.vehicle_type].toLowerCase()} drivers near you…</Body> : null}
        {ride.status === 'driver_arrived' ? <Body>Share the PIN with your driver to start the trip.</Body> : null}
        {ride.status === 'in_progress' ? <Body muted>Heading to {shortAddress(ride.drop.lat, ride.drop.lng, ride.drop.address)}</Body> : null}

        {ride.status === 'completed' ? (
          <Completed ride={ride} />
        ) : isFinished(ride.status) ? (
          <Button title="Book another ride" onPress={() => router.replace('/rider')} />
        ) : (
          <Row style={{ justifyContent: 'space-between' }}>
            <Body style={styles.strong}>{formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise)} · Cash</Body>
            {cancellable ? <Button title="Cancel" kind="secondary" onPress={cancel} loading={busy} /> : null}
          </Row>
        )}
        <ErrorText message={error} />
      </Sheet>
    </View>
  );
}

function Completed({ ride }: { ride: Ride }) {
  const { api } = useSession();
  const [stars, setStars] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    try {
      if (stars) await api.rate(ride.id, stars);
      router.replace('/rider');
    } catch (e) {
      // Already rated (e.g. on another device) is fine; anything else is shown.
      if (e instanceof ApiError && e.status === 409) router.replace('/rider');
      else setError(e instanceof ApiError ? e.message : 'Could not send rating');
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: space.md }}>
      <Body>Pay <Text style={styles.strong}>{formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise)}</Text> in cash to your driver.</Body>
      <Body muted>Rate {ride.driver?.name ?? 'your driver'}</Body>
      <Row style={{ justifyContent: 'center', gap: space.md }}>
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable key={n} onPress={() => setStars(n)} accessibilityLabel={`${n} stars`}>
            <Text style={{ fontSize: 36, color: n <= stars ? colors.warning : colors.border }}>★</Text>
          </Pressable>
        ))}
      </Row>
      <ErrorText message={error} />
      <Button title={stars ? 'Submit' : 'Skip'} onPress={submit} loading={busy} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.lg },
  driverRow: { backgroundColor: colors.surface, borderRadius: 14, padding: space.md },
  strong: { fontSize: 17, fontWeight: '700', color: colors.text },
  pinBox: { alignItems: 'center', backgroundColor: colors.primary, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 6 },
  pinLabel: { color: colors.primaryText, fontSize: 11, fontWeight: '600' },
  pin: { color: colors.primaryText, fontSize: 22, fontWeight: '800', letterSpacing: 4 },
});
