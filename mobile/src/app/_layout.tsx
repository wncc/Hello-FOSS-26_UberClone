import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { Loading } from '@/components/ui';
import { APP_VARIANT } from '@/lib/config';
import { SessionProvider, useSession } from '@/lib/session';
import { LanguageProvider, useLanguage } from '@/lib/i18n';

function RootStack() {
  const { ready, user } = useSession();
  const { ready: languageReady } = useLanguage();
  if (!ready || !languageReady) return <Loading />;
  const signedIn = !!user;
  const named = signedIn && !!user.name;
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="login" />
      </Stack.Protected>
      <Stack.Protected guard={signedIn && !named}>
        <Stack.Screen name="name" />
      </Stack.Protected>
      <Stack.Protected guard={named && APP_VARIANT === 'rider'}>
        <Stack.Screen name="rider" />
      </Stack.Protected>
      <Stack.Protected guard={named && APP_VARIANT === 'driver'}>
        <Stack.Screen name="driver" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <LanguageProvider>
      <SessionProvider>
        <StatusBar style="dark" />
        <RootStack />
      </SessionProvider>
    </LanguageProvider>
  );
}
