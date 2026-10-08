import { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '@/lib/api';
import { VEHICLE_ICON, formatFare, shortAddress } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { Ride } from '@/lib/types';

import { Body, ErrorText, colors, space } from './ui';

const STATUS: Record<Ride['status'], string> = {
  searching: 'Searching', driver_assigned: 'Ongoing', driver_arrived: 'Ongoing', in_progress: 'Ongoing',
  completed: 'Completed', cancelled: 'Cancelled', no_drivers: 'No drivers',
};

/** Past rides for the logged-in rider or driver; drivers also see today's cash earnings. */
export function RideHistory({ showEarnings }: { showEarnings?: boolean }) {
  const { api } = useSession();
  const [rides, setRides] = useState<Ride[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRides = useCallback(() => api.history(50)
    .then((r) => {
      setRides(r);
      setError(null);
    })
    .catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load rides'))
    .finally(() => setLoading(false)), [api]);

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

const styles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: 12, backgroundColor: colors.surface },
  route: { fontSize: 15, fontWeight: '600', color: colors.text },
  meta: { fontSize: 13, color: colors.muted },
  fare: { fontSize: 15, fontWeight: '700', color: colors.text },
  earnings: { backgroundColor: colors.primary, borderRadius: 14, padding: space.md },
  earningsLabel: { color: colors.primaryText, opacity: 0.8 },
  earningsValue: { color: colors.primaryText, fontSize: 28, fontWeight: '800' },
});
