import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Loading, Row, Sheet, Title, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { confirmAction } from '@/lib/dialogs';
import { useLanguage } from '@/lib/i18n';
import { applyRiderEvent } from '@/lib/rideState';
import { useServerEvents, useSession } from '@/lib/session';
import { useRideRoute } from '@/lib/useRideRoute';
import { formatFare, isFinished, shortAddress } from '@/lib/format';
import { VEHICLE_ICON } from '@/lib/format';
import type { Ride, RideStatus, VehicleType } from '@/lib/types';

const POLL_MS = 10_000;

export default function RiderRide() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { api } = useSession();
  const { t } = useLanguage();
  const [ride, setRide] = useState<Ride | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const roads = useRideRoute(id, ride?.status);

  const vehicleName = (vehicle: VehicleType) => {
    switch (vehicle) {
      case 'bike': return t('bike');
      case 'auto_rickshaw': return t('auto');
      case 'car': return t('cab');
    }
  };

  const statusText = (status: RideStatus) => {
    switch (status) {
      case 'searching': return t('findingDriver');
      case 'driver_assigned': return t('driverOnWay');
      case 'driver_arrived': return t('driverArrived');
      case 'in_progress': return t('onTrip');
      case 'completed': return t('tripCompleted');
      case 'cancelled': return t('rideCancelled');
      case 'no_drivers': return t('noDrivers');
    }
  };

  const load = useCallback(() => {
    api.ride(id)
      .then(setRide)
      .catch((e) => setError(e instanceof ApiError ? e.message : t('couldNotLoadRide')));
  }, [api, id, t]);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useServerEvents((event) => {
    setRide((current) => current ? applyRiderEvent(current, event) : current);
    if (event.event === 'ride:driver_assigned' || event.event === 'ride:completed') load();
  });

  function cancel() {
    confirmAction(
      t('cancelRideQuestion'),
      t('riderMayBeOnWay'),
      t('cancelRide'),
      async () => {
        setBusy(true);
        try {
          setRide(await api.cancel(id, 'cancelled by rider'));
        } catch (e) {
          setError(e instanceof ApiError ? e.message : t('couldNotCancel'));
        } finally {
          setBusy(false);
        }
      },
    );
  }

  if (!ride) {
    return error
      ? <View style={styles.center}><ErrorText message={error} /></View>
      : <Loading />;
  }

  const driverPos =
    ride.driver?.lat != null && ride.driver?.lng != null
      ? { lat: ride.driver.lat, lng: ride.driver.lng }
      : null;

  const cancellable = ['searching', 'driver_assigned', 'driver_arrived'].includes(ride.status);
  const fare = formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise);

  return (
    <View style={{ flex: 1 }}>
      <RideMap
        initialCenter={ride.pickup}
        pickup={ride.pickup}
        drop={ride.drop}
        driver={driverPos}
        bottomInset={320}
        route={roads?.trip}
        approach={ride.status === 'driver_assigned' ? roads?.approach : null}
      />

      <Sheet>
        <Title style={{ fontSize: 20 }}>{statusText(ride.status)}</Title>

        {ride.driver && !isFinished(ride.status) ? (
          <Row style={styles.driverRow}>
            <Text style={{ fontSize: 32 }}>{VEHICLE_ICON[ride.vehicle_type]}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.strong}>
                {ride.driver.name ?? t('yourDriver')}
                {ride.driver.rating ? ` · ★ ${ride.driver.rating}` : ''}
              </Text>
              <Body muted>
                {ride.driver.vehicle_number}
                {ride.driver.vehicle_model ? ` · ${ride.driver.vehicle_model}` : ''}
              </Body>
            </View>
            {ride.pin && ride.status !== 'in_progress' ? (
              <View style={styles.pinBox}>
                <Text style={styles.pinLabel}>{t('pin')}</Text>
                <Text style={styles.pin}>{ride.pin}</Text>
              </View>
            ) : null}
          </Row>
        ) : null}

        {ride.status === 'searching' ? (
          <Body muted>{t('pingingDrivers', { vehicle: vehicleName(ride.vehicle_type) })}</Body>
        ) : null}

        {ride.status === 'driver_arrived' ? (
          <Body>{t('sharePin')}</Body>
        ) : null}

        {ride.status === 'in_progress' ? (
          <Body muted>
            {t('headingTo', {
              address: shortAddress(ride.drop.lat, ride.drop.lng, ride.drop.address),
            })}
          </Body>
        ) : null}

        {ride.status === 'completed' ? (
          <Completed ride={ride} />
        ) : isFinished(ride.status) ? (
          <Button title={t('bookAnotherRide')} onPress={() => router.replace('/rider')} />
        ) : (
          <Row style={{ justifyContent: 'space-between' }}>
            <Body style={styles.strong}>{fare} · {t('cash')}</Body>
            {cancellable ? (
              <Button
                title={t('cancel')}
                kind="secondary"
                onPress={cancel}
                loading={busy}
              />
            ) : null}
          </Row>
        )}

        <ErrorText message={error} />
      </Sheet>
    </View>
  );
}

function Completed({ ride }: { ride: Ride }) {
  const { api } = useSession();
  const { t } = useLanguage();
  const [stars, setStars] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fare = formatFare(ride.fare_final_paise ?? ride.fare_estimate_paise);
  const driverName = ride.driver?.name ?? t('yourDriver');

  async function submit() {
    setBusy(true);
    try {
      if (stars) await api.rate(ride.id, stars);
      router.replace('/rider');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        router.replace('/rider');
      } else {
        setError(e instanceof ApiError ? e.message : t('couldNotSendRating'));
        setBusy(false);
      }
    }
  }

  return (
    <View style={{ gap: space.md }}>
      <Body>{t('payCash', { fare })}</Body>
      <Body muted>{t('rateDriver', { name: driverName })}</Body>

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

      <ErrorText message={error} />
      <Button
        title={stars ? t('submit') : t('skip')}
        onPress={submit}
        loading={busy}
      />
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
  driverRow: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: space.md,
  },
  strong: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.text,
  },
  pinBox: {
    alignItems: 'center',
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  pinLabel: {
    color: colors.primaryText,
    fontSize: 11,
    fontWeight: '600',
  },
  pin: {
    color: colors.primaryText,
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: 4,
  },
});
