// Separate bundler caches for the rider and driver apps. EXPO_PUBLIC_APP_VARIANT is inlined at
// build time, so a shared cache can serve the rider app when the driver app was asked for.
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');
const { FileStore } = require('metro-cache');

const config = getDefaultConfig(__dirname);
const variant = process.env.EXPO_PUBLIC_APP_VARIANT === 'driver' ? 'driver' : 'rider';
config.cacheStores = [new FileStore({ root: path.join(__dirname, 'node_modules', '.cache', `metro-${variant}`) })];

module.exports = config;
