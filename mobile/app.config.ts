import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * One codebase, two apps: EXPO_PUBLIC_APP_VARIANT=rider (default) or driver.
 * Each variant gets its own name, scheme and bundle id so both can be installed side by side.
 */
const variant = process.env.EXPO_PUBLIC_APP_VARIANT === 'driver' ? 'driver' : 'rider';
const isDriver = variant === 'driver';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: isDriver ? 'Ride Driver' : 'Ride',
  slug: isDriver ? 'ride-driver' : 'ride',
  scheme: isDriver ? 'ridedriver' : 'ride',
  ios: { ...config.ios, bundleIdentifier: isDriver ? 'in.ride.driver' : 'in.ride.app' },
  android: { ...config.android, package: isDriver ? 'in.ride.driver' : 'in.ride.app' },
  plugins: [
    ...(config.plugins ?? []),
    [
      'expo-location',
      {
        locationWhenInUsePermission: isDriver
          ? 'Your location is shared with riders and used to send you nearby ride requests while you are online.'
          : 'Your location is used to set your pickup point.',
      },
    ],
  ],
  extra: { ...config.extra, variant },
});
