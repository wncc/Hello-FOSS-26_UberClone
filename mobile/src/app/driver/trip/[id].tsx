import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Input, Loading, Row, Sheet, Title, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { confirmAction, notify } from '@/lib/dialogs';
import { directionsUrl, formatFare, shortAddress } from '@/lib/format';
import { useDriverLocationReporter } from '@/lib/location';
import { useServerEvents, useSession } from '@/lib/session';
import { useRideRoute } from '@/lib/useRideRoute';
import type { Ride } from '@/lib/types';

export default function DriverTrip() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useSession();
  const [ride, setRide] = useState<Ride | null>(null);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = !!ride && ['driver_assigned', 'driver_arrived', 'in_progress'].includes(ride.status);
  const { last } = useDriverLocationReporter(live);
  const roads = useRideRoute(id, ride?.status);

  const load = useCallback(() => {
    api.ride(id).then(setRide).catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load the ride'));
  }, [api, id]);

  useEffect(load, [load]);

  useServerEvents((e) => {
    if (e.event === 'ride:cancelled' && e.data.ride_id === id) {
      notify('Ride cancelled', 'The rider cancelled this ride.');
      router.replace('/driver');
    }
  });

  async function step(action: () => Promise<Ride>) {
    setBusy(true);
    setError(null);
    try {
      setRide(await action());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    confirmAction('Cancel this ride?', 'The rider will be matched with another driver.', 'Cancel ride', async () => {
      try {
        await api.cancel(id, 'cancelled by driver');
        router.replace('/driver');
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Could not cancel');
      }
    });
  }

  if (!ride) return error ? <View style={styles.center}><ErrorText message={error} /></View> : <Loading />;

  const target = ride.status === 'in_progress' ? ride.drop : ride.pickup;
  const fare = formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise);

  return (
    <View style={{ flex: 1 }}>
      <RideMap initialCenter={ride.pickup} pickup={ride.status === 'in_progress' ? null : ride.pickup} drop={ride.drop}
               driver={last} bottomInset={320} route={roads?.trip}
               approach={ride.status === 'driver_assigned' ? roads?.approach : null} />
      <Sheet>
        <Row style={{ justifyContent: 'space-between' }}>
          <Title style={{ fontSize: 20 }}>{ride.rider?.name ?? 'Rider'}{ride.rider?.rating ? ` · ★ ${ride.rider.rating}` : ''}</Title>
          <Text style={styles.fare}>{fare}</Text>
        </Row>

        {ride.status === 'driver_assigned' ? (
          <>
            <Body>Pick up at {shortAddress(ride.pickup.lat, ride.pickup.lng, ride.pickup.address)}</Body>
            <Row>
              <Button title="Navigate" kind="secondary" onPress={() => Linking.openURL(directionsUrl(target))} style={{ flex: 1 }} />
              <Button title="I've arrived" onPress={() => step(() => api.arrived(id))} loading={busy} style={{ flex: 1 }} />
            </Row>
          </>
        ) : null}

        {ride.status === 'driver_arrived' ? (
          <>
            <Body>Ask the rider for their 4-digit PIN.</Body>
            <Input value={pin} onChangeText={(t) => setPin(t.replace(/\D/g, ''))} keyboardType="number-pad" maxLength={4}
                   placeholder="PIN" style={{ fontSize: 24, letterSpacing: 8, textAlign: 'center' }} />
            <Button title="Start trip" onPress={() => step(() => api.start(id, pin))} loading={busy} disabled={pin.length !== 4} />
          </>
        ) : null}

        {ride.status === 'in_progress' ? (
          <>
            <Body>Drop at {shortAddress(ride.drop.lat, ride.drop.lng, ride.drop.address)}</Body>
            <Row>
              <Button title="Navigate" kind="secondary" onPress={() => Linking.openURL(directionsUrl(target))} style={{ flex: 1 }} />
              <Button title="Complete trip" kind="accent" onPress={() => step(() => api.complete(id))} loading={busy} style={{ flex: 1 }} />
            </Row>
          </>
        ) : null}

        {ride.status === 'completed' ? <Finished ride={ride} /> : null}

        {ride.status === 'cancelled' || ride.status === 'no_drivers' ? (
          <>
            <Body>This ride was cancelled.</Body>
            <Button title="Back to home" onPress={() => router.replace('/driver')} />
          </>
        ) : null}

        {ride.status === 'driver_assigned' || ride.status === 'driver_arrived' ? (
          <Button title="Cancel ride" kind="secondary" onPress={cancel} />
        ) : null}
        <ErrorText message={error} />
      </Sheet>
    </View>
  );
}

function Finished({ ride }: { ride: Ride }) {
  const { api } = useSession();
  const [stars, setStars] = useState(0);
  const [busy, setBusy] = useState(false);

  async function done() {
    setBusy(true);
    if (stars) await api.rate(ride.id, stars).catch(() => {});   // a failed rating shouldn't block the next ride
    router.replace('/driver');
  }

  return (
    <View style={{ gap: space.md }}>
      <Body>Collect <Text style={styles.fare}>{formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise)}</Text> in cash.</Body>
      <Body muted>Rate the rider</Body>
      <Row style={{ justifyContent: 'center', gap: space.md }}>
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable key={n} onPress={() => setStars(n)} accessibilityLabel={`${n} stars`}>
            <Text style={{ fontSize: 36, color: n <= stars ? colors.warning : colors.border }}>★</Text>
          </Pressable>
        ))}
      </Row>
      <Button title="Done" onPress={done} loading={busy} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.lg },
  fare: { fontSize: 18, fontWeight: '800', color: colors.text },
});
