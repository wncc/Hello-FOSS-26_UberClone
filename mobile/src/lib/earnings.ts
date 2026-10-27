import type { EarningsDay } from './types';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** 'Mon', 'Tue', … for a 'YYYY-MM-DD' day, without Intl and without the phone's timezone shifting the date. */
export function weekdayLabel(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  return WEEKDAYS[new Date(y, m - 1, d).getDay()];
}

/** Bar length for each day as a share (0–1) of the best day, so the best day fills the row. */
export function barShares(perDay: EarningsDay[]): number[] {
  const best = Math.max(0, ...perDay.map((d) => d.earnings_paise));
  return perDay.map((d) => (best > 0 ? d.earnings_paise / best : 0));
}
