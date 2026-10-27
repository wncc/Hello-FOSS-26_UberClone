import { expect, test } from '@jest/globals';
import { dark, light, paletteFor, type Palette } from '../theme';

test('follows the phone setting; anything unknown is light', () => {
  expect(paletteFor('dark')).toBe(dark);
  expect(paletteFor('light')).toBe(light);
  expect(paletteFor(null)).toBe(light);
  expect(paletteFor(undefined)).toBe(light);
});

test('both palettes define the same colours', () => {
  expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
});

/** WCAG relative luminance and contrast ratio, for '#rrggbb' colours. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

test.each<[string, Palette]>([['light', light], ['dark', dark]])('%s text is readable (WCAG AA, 4.5:1)', (_, t) => {
  expect(contrast(t.text, t.bg)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t.text, t.surface)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t.muted, t.bg)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t.danger, t.bg)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(t.primaryText, t.primary)).toBeGreaterThanOrEqual(4.5);   // buttons, PIN box, earnings card
});
