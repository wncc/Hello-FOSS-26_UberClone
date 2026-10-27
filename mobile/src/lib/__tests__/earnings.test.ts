import { expect, test } from '@jest/globals';
import { barShares, weekdayLabel } from '../earnings';

test('weekday labels come from the calendar date, not the phone timezone', () => {
  expect(weekdayLabel('2026-10-28')).toBe('Wed');
  expect(weekdayLabel('2026-10-25')).toBe('Sun');
  expect(weekdayLabel('2026-01-01')).toBe('Thu');
});

test('bars are scaled to the best day', () => {
  const day = (earnings_paise: number) => ({ day: '2026-10-28', earnings_paise, trips: earnings_paise ? 1 : 0 });
  expect(barShares([day(0), day(50000), day(100000)])).toEqual([0, 0.5, 1]);
  expect(barShares([day(0), day(0)])).toEqual([0, 0]);     // an idle week draws no bars, no NaN
  expect(barShares([])).toEqual([]);
});
