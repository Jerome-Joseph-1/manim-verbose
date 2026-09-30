import { describe, expect, it } from 'vitest';
import { MANIM_COLORS, SWATCH_ROWS, colorLabel, colorToHex, contrastText, isColor, normalizeColor } from './colors';

describe('colors', () => {
  it('knows manim names and hex codes', () => {
    expect(isColor('BLUE')).toBe(true);
    expect(isColor('blue_e')).toBe(true);
    expect(isColor('GRAY_A')).toBe(true);
    expect(isColor('#58C4DD')).toBe(true);
    expect(isColor('#abc')).toBe(true);
    expect(isColor('#58C4DD80')).toBe(true);
    expect(isColor('blu')).toBe(false);
    expect(isColor('#12345')).toBe(false);
  });

  it('writes names in capitals and keeps hex as typed', () => {
    expect(normalizeColor(' red e ')).toBe('RED_E');
    expect(normalizeColor('#58c4dd')).toBe('#58c4dd');
    expect(normalizeColor('nope')).toBeNull();
  });

  it('turns any color into hex for drawing', () => {
    expect(colorToHex('BLUE')).toBe('#58C4DD');
    expect(colorToHex('#abc')).toBe('#AABBCC');
    expect(colorToHex('#58C4DD80')).toBe('#58C4DD');
    expect(colorToHex('what')).toBeNull();
    expect(colorToHex(null)).toBeNull();
  });

  it('offers only real colors as swatches', () => {
    for (const name of SWATCH_ROWS.flat()) expect(MANIM_COLORS[name], name).toMatch(/^#[0-9A-F]{6}$/);
  });

  it('labels and contrasts', () => {
    expect(colorLabel('BLUE_E')).toBe('Blue E');
    expect(contrastText('#FFFF00')).toBe('#000000');
    expect(contrastText('#1C758A')).toBe('#FFFFFF');
  });
});
