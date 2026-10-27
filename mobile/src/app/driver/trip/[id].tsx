import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Input, Loading, Row, Sheet, Title, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { confirmAction, notify } from '@/lib/dialogs';
import { useLanguage } from '@/lib/i18n';
import { directionsUrl, formatFare, shortAddress } from '@/lib/format';
import { useDriverLocationReporter } from '@/lib/location';
import { useServerEvents, useSession } from '@/lib/session';
import { useRideRoute } from '@/lib/useRideRoute';
import type { Ride } from '@/lib/types';

export default function DriverTrip() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useSession();
  const { t } = useLanguage();

  const [ride, setRide] = useState<Ride | null>(null);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const live = !!ride && ['driver_assigned', 'driver_arrived', 'in_progress'].includes(ride.status);
  const { last } = useDriverLocationReporter(live);
  const roads = useRideRoute(id, ride?.status);

  const load = useCallback(() => {
    api.ride(id)
      .then(setRide)
      .catch((e) => setError(e instanceof ApiError ? e.message : t('couldNotLoadRide')));
  }, [api, id, t]);

  useEffect(load, [load]);

  useServerEvents((event) => {
    if (event.event === 'ride:cancelled' && event.data.ride_id === id) {
      notify(t('rideCancelled'), t('cancelledMessage'));
      router.replace('/driver');
    }
  });

  async function step(action: () => Promise<Ride>) {
    setBusy(true);
    setError(null);

    try {
      setRide(await action());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('somethingWentWrong'));
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    confirmAction(
      t('cancelTripQuestion'),
      t('riderRematched'),
      t('cancelRide'),
      async () => {
        try {
          await api.cancel(id, 'cancelled by driver');
          router.replace('/driver');
        } catch (e) {
          setError(e instanceof ApiError ? e.message : t('couldNotCancel'));
        }
      },
      t('back'),
    );
  }

  if (!ride) {
    return error
      ? <View style={styles.center}><ErrorText message={error} /></View>
      : <Loading />;
  }

  const target = ride.status === 'in_progress' ? ride.drop : ride.pickup;
  const fare = formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise);

  return (
    <View style={{ flex: 1 }}>
      <RideMap
        initialCenter={ride.pickup}
        pickup={ride.status === 'in_progress' ? null : ride.pickup}
        drop={ride.drop}
        driver={last}
        bottomInset={320}
        route={roads?.trip}
        approach={ride.status === 'driver_assigned' ? roads?.approach : null}
      />

      <Sheet>
        <Row style={{ justifyContent: 'space-between' }}>
          <Title style={{ fontSize: 20 }}>
            {ride.rider?.name ?? t('rider')}
            {ride.rider?.rating ? ` · ★ ${ride.rider.rating}` : ''}
          </Title>
          <Text style={styles.fare}>{fare}</Text>
        </Row>

        {ride.status === 'driver_assigned' ? (
          <>
            <Body>
              {t('pickupAt', {
                address: shortAddress(
                  ride.pickup.lat,
                  ride.pickup.lng,
                  ride.pickup.address,
                ),
              })}
            </Body>
            <Row>
              <Button
                title={t('navigate')}
                kind="secondary"
                onPress={() => Linking.openURL(directionsUrl(target))}
                style={{ flex: 1 }}
              />
              <Button
                title={t('arrived')}
                onPress={() => step(() => api.arrived(id))}
                loading={busy}
                style={{ flex: 1 }}
              />
            </Row>
          </>
        ) : null}

        {ride.status === 'driver_arrived' ? (
          <>
            <Body>{t('askPin')}</Body>
            <Input
              value={pin}
              onChangeText={(value) => setPin(value.replace(/\D/g, ''))}
              keyboardType="number-pad"
              maxLength={4}
              placeholder={t('pin')}
              style={{ fontSize: 24, letterSpacing: 8, textAlign: 'center' }}
            />
            <Button
              title={t('startTrip')}
              onPress={() => step(() => api.start(id, pin))}
              loading={busy}
              disabled={pin.length !== 4}
            />
          </>
        ) : null}

        {ride.status === 'in_progress' ? (
          <>
            <Body>
              {t('dropAt', {
                address: shortAddress(
                  ride.drop.lat,
                  ride.drop.lng,
                  ride.drop.address,
                ),
              })}
            </Body>
            <Row>
              <Button
                title={t('navigate')}
                kind="secondary"
                onPress={() => Linking.openURL(directionsUrl(target))}
                style={{ flex: 1 }}
              />
              <Button
                title={t('completeTrip')}
                kind="accent"
                onPress={() => step(() => api.complete(id))}
                loading={busy}
                style={{ flex: 1 }}
              />
            </Row>
          </>
        ) : null}

        {ride.status === 'completed' ? <Finished ride={ride} /> : null}

        {ride.status === 'cancelled' || ride.status === 'no_drivers' ? (
          <>
            <Body>{t('cancelledMessage')}</Body>
            <Button
              title={t('backHome')}
              onPress={() => router.replace('/driver')}
            />
          </>
        ) : null}

        {ride.status === 'driver_assigned' || ride.status === 'driver_arrived' ? (
          <Button
            title={t('cancelRide')}
            kind="secondary"
            onPress={cancel}
          />
        ) : null}

        <ErrorText message={error} />
      </Sheet>
    </View>
  );
}

function Finished({ ride }: { ride: Ride }) {
  const { api } = useSession();
  const { t } = useLanguage();
  const [stars, setStars] = useState(0);
  const [busy, setBusy] = useState(false);

  async function done() {
    setBusy(true);
    if (stars) await api.rate(ride.id, stars).catch(() => {});
    router.replace('/driver');
  }

  const fare = formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise);

  return (
    <View style={{ gap: space.md }}>
      <Body>{t('collectCash', { fare })}</Body>
      <Body muted>{t('rateRider')}</Body>

      <Row style={{ justifyContent: 'center', gap: space.md }}>
        {[1, 2, 3, 4, 5].map((number) => (
          <Pressable
            key={number}
            onPress={() => setStars(number)}
            accessibilityRole="button"
            accessibilityLabel={t('stars', { count: number })}
          >
            <Text style={{
              fontSize: 36,
              color: number <= stars ? colors.warning : colors.border,
            }}>
              ★
            </Text>
          </Pressable>
        ))}
      </Row>

      <Button title={t('done')} onPress={done} loading={busy} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.lg,
  },
  fare: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.text,
  },
});
