import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Body, Button, ErrorText, Input, Row, Screen, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { VEHICLE_ICON, VEHICLE_LABEL, VEHICLE_ORDER } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { VehicleType } from '@/lib/types';

export default function Vehicle() {
  const { api } = useSession();
  const [vehicle, setVehicle] = useState<VehicleType>('auto_rickshaw');
  const [number, setNumber] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.driverProfile()
      .then((p) => {
        setVehicle(p.vehicle_type);
        setNumber(p.vehicle_number);
        setModel(p.vehicle_model ?? '');
      })
      .catch(() => {});   // no profile yet: first-time setup
  }, [api]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.saveDriverProfile(vehicle, number.trim(), model.trim() || undefined);
      if (router.canGoBack()) router.back();
      else router.replace('/driver');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save');
      setBusy(false);
    }
  }

  return (
    <Screen style={{ gap: space.lg }}>
      <Body muted>Riders see these details when you’re assigned to their ride.</Body>
      <Row>
        {VEHICLE_ORDER.map((v) => (
          <Pressable key={v} onPress={() => setVehicle(v)} style={[styles.choice, vehicle === v && styles.selected]}>
            <Text style={{ fontSize: 30 }}>{VEHICLE_ICON[v]}</Text>
            <Text style={styles.choiceText}>{VEHICLE_LABEL[v]}</Text>
          </Pressable>
        ))}
      </Row>
      <Input label="Registration number" value={number} onChangeText={setNumber} autoCapitalize="characters"
             placeholder="KA 01 AB 1234" maxLength={16} />
      <Input label="Model (optional)" value={model} onChangeText={setModel} placeholder="e.g. Bajaj RE" maxLength={60} />
      <ErrorText message={error} />
      <View style={{ flex: 1 }} />
      <Button title="Save" onPress={save} loading={busy} disabled={number.trim().length < 4} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  choice: {
    flex: 1, alignItems: 'center', padding: space.md, borderRadius: 12, borderWidth: 2, borderColor: colors.border, gap: 4,
  },
  selected: { borderColor: colors.primary, backgroundColor: colors.surface },
  choiceText: { fontWeight: '600', color: colors.text },
});
