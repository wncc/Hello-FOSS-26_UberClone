/** The two colour palettes. Which one is active follows the phone's light/dark setting (see useTheme in ui.tsx). */

export interface Palette {
  bg: string;
  surface: string;
  border: string;
  text: string;
  muted: string;
  primary: string;
  primaryText: string;
  accent: string;
  danger: string;
  warning: string;
}

export const light: Palette = {
  bg: '#FFFFFF',
  surface: '#F3F4F6',
  border: '#E5E7EB',
  text: '#111827',
  muted: '#6B7280',
  primary: '#111827',
  primaryText: '#FFFFFF',
  accent: '#10B981',
  danger: '#DC2626',
  warning: '#F59E0B',
};

export const dark: Palette = {
  bg: '#0F172A',
  surface: '#1E293B',
  border: '#334155',
  text: '#F1F5F9',
  muted: '#94A3B8',
  primary: '#F1F5F9',
  primaryText: '#0F172A',
  accent: '#34D399',
  danger: '#F87171',
  warning: '#FBBF24',
};

/** The palette for a colour scheme as React Native reports it; anything but 'dark' is light. */
export function paletteFor(scheme: string | null | undefined): Palette {
  return scheme === 'dark' ? dark : light;
}

/** The map page's own backgrounds, shown behind and between tiles while they load. */
export const MAP_BG = { light: '#e5e7eb', dark: '#0f172a' };
