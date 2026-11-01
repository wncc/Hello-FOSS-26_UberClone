import { expect, test } from '@jest/globals';
import { directionsUrl, formatDistance, formatDuration, formatFare, isFinished, normalizeIndianPhone, riderStatusText } from '../format';

test('fares in rupees', () => {
  expect(formatFare(12300)).toBe('₹123');
  expect(formatFare(123450)).toBe('₹1,234.50');
  expect(formatFare(15000000)).toBe('₹1,50,000');   // Indian digit grouping
  expect(formatFare(1234567890)).toBe('₹1,23,45,678.90');
  expect(formatFare(5)).toBe('₹0.05');
});

test('distances and durations', () => {
  expect(formatDistance(843)).toBe('840 m');
  expect(formatDistance(4230)).toBe('4.2 km');
  expect(formatDuration(20)).toBe('1 min');
  expect(formatDuration(25 * 60)).toBe('25 min');
  expect(formatDuration(65 * 60)).toBe('1 h 5 min');
  expect(formatDuration(120 * 60)).toBe('2 h');
});

test('indian mobile numbers', () => {
  expect(normalizeIndianPhone('98450 12345')).toBe('+919845012345');
  expect(normalizeIndianPhone('+91 98450-12345')).toBe('+919845012345');
  expect(normalizeIndianPhone('09845012345')).toBe('+919845012345');
  expect(normalizeIndianPhone('12345')).toBeNull();
  expect(normalizeIndianPhone('5845012345')).toBeNull();   // must start with 6-9
});

test('finished statuses and directions link', () => {
  expect(isFinished('completed')).toBe(true);
  expect(isFinished('in_progress')).toBe(false);
  expect(directionsUrl({ lat: 12.97, lng: 77.59 })).toContain('destination=12.97,77.59');
});

test('rider status text shows live arrival countdown', () => {
  expect(riderStatusText('driver_assigned')).toBe('Driver is on the way');
  expect(riderStatusText('driver_assigned', null)).toBe('Driver is on the way');
  expect(riderStatusText('driver_assigned', 240)).toBe('Arriving in 4 min');
  expect(riderStatusText('driver_assigned', 20)).toBe('Arriving in 1 min');
  expect(riderStatusText('driver_arrived', 120)).toBe('Driver has arrived');
});