import { Stack } from 'expo-router';

export default function RiderLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="ride/[id]" options={{ gestureEnabled: false }} />
      <Stack.Screen name="history" options={{ headerShown: true, title: 'Your rides' }} />
    </Stack>
  );
}
