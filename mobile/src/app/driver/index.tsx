import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useReducer, useState } from 'react';
import { StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Row, Sheet, Title, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useLanguage } from '@/lib/i18n';
import { VEHICLE_ICON, formatDistance, formatDuration, formatFare, shortAddress } from '@/lib/format';
import { DEFAULT_CENTER, useDriverLocationReporter } from '@/lib/location';
import { driverHome, secondsLeft } from '@/lib/rideState';
import { useServerEvents, useSession } from '@/lib/session';
import type { DriverProfile } from '@/lib/types';

export default function DriverHome() {
  const { api, user, signOut, socketConnected } = useSession();
  const { t } = useLanguage();
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const [state, dispatch] = useReducer(driverHome, { mode: 'offline' });
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const online = state.mode !== 'offline';
  const { last, error: gpsError } = useDriverLocationReporter(online);

  useFocusEffect(useCallback(() => {
    let alive = true;

    (async () => {
      try {
        const p = await api.driverProfile();
        if (!alive) return;

        setProfile(p);
        const active = await api.activeRide();

        if (active) {
          router.replace(`/driver/trip/${active.id}`);
          return;
        }

        dispatch({ type: 'trip_done' });
        dispatch({ type: 'online', online: p.is_online });

        if (p.is_online) {
          const offer = await api.currentOffer();
          if (offer && alive) {
            dispatch({
              type: 'event',
              event: { event: 'ride:ping', data: offer },
              now: Date.now(),
            });
          }
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          router.replace('/driver/vehicle');
        } else if (alive) {
          setError(e instanceof ApiError ? e.message : t('couldNotReachServer'));
        }
      }
    })();

    return () => {
      alive = false;
    };
  }, [api, t]));

  useServerEvents((event) => {
    dispatch({ type: 'event', event, now: Date.now() });
  });

  useEffect(() => {
    if (state.mode !== 'offered') return;

    const timer = setInterval(() => {
      setNow(Date.now());
      dispatch({ type: 'tick', now: Date.now() });
    }, 500);

    return () => clearInterval(timer);
  }, [state.mode]);

  useEffect(() => {
    if (state.mode === 'assigned') {
      router.replace(`/driver/trip/${state.rideId}`);
    }
  }, [state]);

  async function toggleOnline(value: boolean) {
    setBusy(true);
    setError(null);

    try {
      const p = await api.setOnline(value);
      setProfile(p);
      dispatch({ type: 'online', online: p.is_online });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('couldNotChangeStatus'));
    } finally {
      setBusy(false);
    }
  }

  async function respond(accept: boolean) {
    if (state.mode !== 'offered') return;

    const rideId = state.offer.ride_id;
    setBusy(true);
    setError(null);

    try {
      if (accept) {
        await api.accept(rideId);
        dispatch({ type: 'accepted' });
      } else {
        await api.reject(rideId);
        dispatch({ type: 'rejected' });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('somethingWentWrong'));
      dispatch({ type: 'rejected' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ flex: 1 }}>
      <RideMap
        initialCenter={last ?? DEFAULT_CENTER}
        driver={last}
        pickup={
          state.mode === 'offered' || state.mode === 'confirming'
            ? state.offer.pickup
            : null
        }
        bottomInset={300}
      />

      <SafeAreaView edges={['top']} style={styles.topBar}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Row style={styles.chip}>
            <Text style={{ fontWeight: '700' }}>
              {online ? `● ${t('online')}` : `○ ${t('offline')}`}
            </Text>
            <Switch
              value={online}
              onValueChange={toggleOnline}
              disabled={busy || profile?.status !== 'approved'}
            />
          </Row>

          <Row>
            <Text style={styles.chip} onPress={() => router.push('/driver/history')}>
              {t('earnings')}
            </Text>
            <Text style={styles.chip} onPress={() => router.push('/driver/vehicle')}>
              {t('vehicle')}
            </Text>
            <Text style={styles.chip} onPress={signOut}>
              {t('logout')}
            </Text>
          </Row>
        </Row>
      </SafeAreaView>

      <Sheet>
        {state.mode === 'offered' ? (
          <>
            <Row style={{ justifyContent: 'space-between' }}>
              <Title style={{ fontSize: 22 }}>
                {t('newRide')} · {formatFare(state.offer.fare_paise)}
              </Title>
              <Text style={styles.countdown}>{secondsLeft(state, now)}s</Text>
            </Row>

            <Body>
              🟢 {shortAddress(
                state.offer.pickup.lat,
                state.offer.pickup.lng,
                state.offer.pickup.address,
              )}
            </Body>
            <Body>
              🔴 {shortAddress(
                state.offer.drop.lat,
                state.offer.drop.lng,
                state.offer.drop.address,
              )}
            </Body>
            <Body muted>
              {t('trip')} {formatDistance(state.offer.distance_m)} ·{' '}
              {formatDuration(state.offer.duration_s)} · {t('cash')}
            </Body>

            {state.offer.pickup_distance_m != null && state.offer.pickup_eta_s != null && (
              <Body style={{ fontWeight: '600' }}>
                📍 {formatDistance(state.offer.pickup_distance_m)} away · {formatDuration(state.offer.pickup_eta_s)}
              </Body>
            )}
            <Body>🟢 {shortAddress(state.offer.pickup.lat, state.offer.pickup.lng, state.offer.pickup.address)}</Body>
            <Body>🔴 {shortAddress(state.offer.drop.lat, state.offer.drop.lng, state.offer.drop.address)}</Body>
            <Body muted>Trip {formatDistance(state.offer.distance_m)} · {formatDuration(state.offer.duration_s)} · Cash</Body>
            <Row>
              <Button
                title={t('decline')}
                kind="secondary"
                onPress={() => respond(false)}
                disabled={busy}
                style={{ flex: 1 }}
              />
              <Button
                title={t('accept')}
                kind="accent"
                onPress={() => respond(true)}
                loading={busy}
                style={{ flex: 2 }}
              />
            </Row>
          </>
        ) : state.mode === 'confirming' ? (
          <>
            <Title style={{ fontSize: 22 }}>{t('confirming')}</Title>
            <Body muted>{t('nearbyDriversHint')}</Body>
          </>
        ) : online ? (
          <>
            <Title style={{ fontSize: 22 }}>{t('findingRides')}</Title>
            <Body muted>
              {t('keepAppOpen')} {socketConnected ? t('connected') : t('reconnecting')}
            </Body>
          </>
        ) : (
          <>
            <Title style={{ fontSize: 22 }}>
              {t('goOfflineGreeting', { name: user?.name?.split(' ')[0] ?? '' })}
            </Title>

            {profile ? (
              <Body muted>
                {VEHICLE_ICON[profile.vehicle_type]} {profile.vehicle_number}
                {profile.status !== 'approved'
                  ? ` · ${t('accountStatus', { status: profile.status })}`
                  : ''}
              </Body>
            ) : null}

            <Button
              title={t('goOnline')}
              onPress={() => toggleOnline(true)}
              loading={busy}
              disabled={profile?.status !== 'approved'}
            />
          </>
        )}

        <ErrorText message={error ?? gpsError} />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  topBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
  },
  chip: {
    backgroundColor: colors.bg,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
    overflow: 'hidden',
    fontWeight: '600',
    color: colors.text,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 6,
    elevation: 4,
  },
  countdown: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.danger,
  },
});
