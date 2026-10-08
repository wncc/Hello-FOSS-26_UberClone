import { Stack } from 'expo-router';

export default function DriverLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="vehicle" options={{ headerShown: true, title: 'Your vehicle' }} />
      <Stack.Screen name="trip/[id]" options={{ gestureEnabled: false }} />
      <Stack.Screen name="history" options={{ headerShown: true, title: 'Rides & earnings' }} />
    </Stack>
  );
}
