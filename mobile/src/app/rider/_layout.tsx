import { Stack } from 'expo-router';

import { useLanguage } from '@/lib/i18n';

export default function RiderLayout() {
  const { t } = useLanguage();

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="ride/[id]" options={{ gestureEnabled: false }} />
      <Stack.Screen
        name="history"
        options={{ headerShown: true, title: t('yourRidesTitle') }}
      />
    </Stack>
  );
}
