import { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/lib/api';
import { barShares, weekdayLabel } from '@/lib/earnings';
import { VEHICLE_ICON, formatFare, shortAddress } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { Earnings, Ride } from '@/lib/types';

import { Body, ErrorText, colors, space } from './ui';

const STATUS: Record<Ride['status'], string> = {
  searching: 'Searching', driver_assigned: 'Ongoing', driver_arrived: 'Ongoing', in_progress: 'Ongoing',
  completed: 'Completed', cancelled: 'Cancelled', no_drivers: 'No drivers',
};

const WEEK_DAYS = 7;

/** Past rides for the logged-in rider or driver; drivers also see today's cash earnings and the week. */
export function RideHistory({ showEarnings }: { showEarnings?: boolean }) {
  const { api } = useSession();
  const [rides, setRides] = useState<Ride[]>([]);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRides = useCallback(() => {
    const calls: Promise<unknown>[] = [api.history(50).then(setRides)];
    if (showEarnings) calls.push(api.earnings(WEEK_DAYS).then(setEarnings));
    return Promise.all(calls)
      .then(() => setError(null))
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load rides'))
      .finally(() => setLoading(false));
  }, [api, showEarnings]);

  useEffect(() => {
    fetchRides();
  }, [fetchRides]);

  function refresh() {
    setLoading(true);
    fetchRides();
  }

  const today = new Date().toDateString();
  const earnedToday = rides
    .filter((r) => r.status === 'completed' && r.completed_at && new Date(r.completed_at).toDateString() === today)
    .reduce((sum, r) => sum + (r.fare_final_paise ?? 0), 0);

  return (
    <FlatList
      data={rides}
      keyExtractor={(r) => r.id}
      contentContainerStyle={{ padding: space.md, gap: space.sm }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} />}
      ListHeaderComponent={
        <View style={{ gap: space.sm }}>
          {showEarnings ? (
            <View style={styles.earnings}>
              <Text style={styles.earningsLabel}>Today’s earnings (cash)</Text>
              <Text style={styles.earningsValue}>{formatFare(earnedToday)}</Text>
              {earnings ? <WeekEarnings earnings={earnings} /> : null}
            </View>
          ) : null}
          <ErrorText message={error} />
        </View>
      }
      ListEmptyComponent={loading ? null : <Body muted>No rides yet.</Body>}
      renderItem={({ item }) => (
        <View style={styles.item}>
          <Text style={{ fontSize: 26 }}>{VEHICLE_ICON[item.vehicle_type]}</Text>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.route} numberOfLines={1}>
              {shortAddress(item.pickup.lat, item.pickup.lng, item.pickup.address)} → {shortAddress(item.drop.lat, item.drop.lng, item.drop.address)}
            </Text>
            <Text style={styles.meta}>{new Date(item.requested_at).toLocaleString('en-IN')} · {STATUS[item.status]}</Text>
          </View>
          <Text style={styles.fare}>{formatFare(item.fare_final_paise ?? item.fare_estimate_paise)}</Text>
        </View>
      )}
    />
  );
}

/** The week's total and a bar per day (days in India time, from the backend), today last. */
function WeekEarnings({ earnings }: { earnings: Earnings }) {
  const shares = barShares(earnings.per_day);
  const last = earnings.per_day.length - 1;
  return (
    <View style={styles.week}>
      <View style={styles.weekRow}>
        <Text style={styles.weekLabel}>Last {earnings.days} days</Text>
        <Text style={styles.weekValue}>
          {formatFare(earnings.total_paise)} · {earnings.trips} {earnings.trips === 1 ? 'trip' : 'trips'}
        </Text>
      </View>
      {earnings.per_day.map((d, i) => (
        <View
          key={d.day}
          style={styles.dayRow}
          accessibilityLabel={`${i === last ? 'Today' : weekdayLabel(d.day)}: ${formatFare(d.earnings_paise)}, ${d.trips} ${d.trips === 1 ? 'trip' : 'trips'}`}
        >
          <Text style={styles.dayLabel}>{i === last ? 'Today' : weekdayLabel(d.day)}</Text>
          <View style={styles.barTrack}>
            <View style={[styles.bar, { width: `${Math.round(shares[i] * 100)}%` as `${number}%` }]} />
          </View>
          <Text style={styles.dayValue}>{d.trips ? formatFare(d.earnings_paise) : '–'}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: 12, backgroundColor: colors.surface },
  route: { fontSize: 15, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.muted },
  fare: { fontSize: 15, fontWeight: '700', color: colors.text },
  earnings: { backgroundColor: colors.primary, borderRadius: 14, padding: space.md },
  earningsLabel: { color: colors.primaryText, opacity: 0.8 },
  earningsValue: { color: colors.primaryText, fontSize: 28, fontWeight: '800' },
  week: { marginTop: space.md, paddingTop: space.md, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.primaryText, gap: space.xs },
  weekRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: space.xs },
  weekLabel: { color: colors.primaryText, opacity: 0.8 },
  weekValue: { color: colors.primaryText, fontSize: 16, fontWeight: '700' },
  dayRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 24 },
  dayLabel: { width: 44, color: colors.primaryText, opacity: 0.8, fontSize: 13 },
  barTrack: { flex: 1, height: 10, borderRadius: 5, backgroundColor: 'rgba(255,255,255,0.15)', overflow: 'hidden' },
  bar: { height: '100%', borderRadius: 5, backgroundColor: colors.accent },
  dayValue: { minWidth: 64, textAlign: 'right', color: colors.primaryText, fontSize: 13, fontWeight: '600' },
});
