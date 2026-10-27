import { Stack } from 'expo-router';

import { useLanguage } from '@/lib/i18n';

export default function DriverLayout() {
  const { t } = useLanguage();

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen
        name="vehicle"
        options={{ headerShown: true, title: t('yourVehicleTitle') }}
      />
      <Stack.Screen name="trip/[id]" options={{ gestureEnabled: false }} />
      <Stack.Screen
        name="history"
        options={{ headerShown: true, title: t('ridesEarningsTitle') }}
      />
    </Stack>
  );
}
