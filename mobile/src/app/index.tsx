import { Redirect } from 'expo-router';

import { APP_VARIANT } from '@/lib/config';
import { useSession } from '@/lib/session';

/** Entry point: send the user to the right place for their session and app variant. */
export default function Index() {
  const { user } = useSession();
  if (!user) return <Redirect href="/login" />;
  if (!user.name) return <Redirect href="/name" />;
  return <Redirect href={APP_VARIANT === 'driver' ? '/driver' : '/rider'} />;
}
