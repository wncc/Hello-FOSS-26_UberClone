import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Body, Button, ErrorText, Input, Row, Screen, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useLanguage } from '@/lib/i18n';
import { VEHICLE_ICON, VEHICLE_ORDER } from '@/lib/format';
import { useSession } from '@/lib/session';
import type { VehicleType } from '@/lib/types';

export default function Vehicle() {
  const { api } = useSession();
  const { t } = useLanguage();

  const [vehicle, setVehicle] = useState<VehicleType>('auto_rickshaw');
  const [number, setNumber] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function vehicleName(value: VehicleType) {
    switch (value) {
      case 'bike': return t('bike');
      case 'auto_rickshaw': return t('auto');
      case 'car': return t('cab');
    }
  }

  useEffect(() => {
    api.driverProfile()
      .then((profile) => {
        setVehicle(profile.vehicle_type);
        setNumber(profile.vehicle_number);
        setModel(profile.vehicle_model ?? '');
      })
      .catch(() => {
        // No profile yet: first-time setup.
      });
  }, [api]);

  async function save() {
    setBusy(true);
    setError(null);

    try {
      await api.saveDriverProfile(
        vehicle,
        number.trim(),
        model.trim() || undefined,
      );

      if (router.canGoBack()) router.back();
      else router.replace('/driver');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('couldNotSave'));
      setBusy(false);
    }
  }

  return (
    <Screen style={{ gap: space.lg }}>
      <Body muted>{t('vehicleDetailsHint')}</Body>

      <Row>
        {VEHICLE_ORDER.map((value) => (
          <Pressable
            key={value}
            accessibilityRole="button"
            accessibilityState={{ selected: vehicle === value }}
            onPress={() => setVehicle(value)}
            style={[
              styles.choice,
              vehicle === value && styles.selected,
            ]}
          >
            <Text style={{ fontSize: 30 }}>{VEHICLE_ICON[value]}</Text>
            <Text style={styles.choiceText}>{vehicleName(value)}</Text>
          </Pressable>
        ))}
      </Row>

      <Input
        label={t('registrationNumber')}
        value={number}
        onChangeText={setNumber}
        autoCapitalize="characters"
        placeholder="KA 01 AB 1234"
        maxLength={16}
      />

      <Input
        label={t('vehicleModel')}
        value={model}
        onChangeText={setModel}
        placeholder="e.g. Bajaj RE"
        maxLength={60}
      />

      <ErrorText message={error} />
      <View style={{ flex: 1 }} />

      <Button
        title={t('save')}
        onPress={save}
        loading={busy}
        disabled={number.trim().length < 4}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  choice: {
    flex: 1,
    alignItems: 'center',
    padding: space.md,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: colors.border,
    gap: 4,
  },
  selected: {
    borderColor: colors.primary,
    backgroundColor: colors.surface,
  },
  choiceText: {
    fontWeight: '600',
    color: colors.text,
  },
});
