import { Stack } from 'expo-router';

import { useTheme } from '@/components/ui';

export default function DriverLayout() {
  const t = useTheme();
  return (
    <Stack screenOptions={{
      headerShown: false, headerStyle: { backgroundColor: t.bg }, headerTintColor: t.text,
      contentStyle: { backgroundColor: t.bg },
    }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="vehicle" options={{ headerShown: true, title: 'Your vehicle' }} />
      <Stack.Screen name="trip/[id]" options={{ gestureEnabled: false }} />
      <Stack.Screen name="history" options={{ headerShown: true, title: 'Rides & earnings' }} />
    </Stack>
  );
}
