/**
 * manim's named colors (manimlib/default_config.yml), for swatches and for telling what a
 * color name looks like. A color in a scene file is a hex code or one of these names.
 */

export const MANIM_COLORS: Record<string, string> = {
  BLUE_E: '#1C758A', BLUE_D: '#29ABCA', BLUE_C: '#58C4DD', BLUE_B: '#9CDCEB', BLUE_A: '#C7E9F1',
  TEAL_E: '#49A88F', TEAL_D: '#55C1A7', TEAL_C: '#5CD0B3', TEAL_B: '#76DDC0', TEAL_A: '#ACEAD7',
  GREEN_E: '#699C52', GREEN_D: '#77B05D', GREEN_C: '#83C167', GREEN_B: '#A6CF8C', GREEN_A: '#C9E2AE',
  YELLOW_E: '#E8C11C', YELLOW_D: '#F4D345', YELLOW_C: '#FFFF00', YELLOW_B: '#FFEA94', YELLOW_A: '#FFF1B6',
  GOLD_E: '#C78D46', GOLD_D: '#E1A158', GOLD_C: '#F0AC5F', GOLD_B: '#F9B775', GOLD_A: '#F7C797',
  RED_E: '#CF5044', RED_D: '#E65A4C', RED_C: '#FC6255', RED_B: '#FF8080', RED_A: '#F7A1A3',
  MAROON_E: '#94424F', MAROON_D: '#A24D61', MAROON_C: '#C55F73', MAROON_B: '#EC92AB', MAROON_A: '#ECABC1',
  PURPLE_E: '#644172', PURPLE_D: '#715582', PURPLE_C: '#9A72AC', PURPLE_B: '#B189C6', PURPLE_A: '#CAA3E8',
  GREY_E: '#222222', GREY_D: '#444444', GREY_C: '#888888', GREY_B: '#BBBBBB', GREY_A: '#DDDDDD',
  WHITE: '#FFFFFF', BLACK: '#000000',
  GREY_BROWN: '#736357', DARK_BROWN: '#8B4513', LIGHT_BROWN: '#CD853F',
  PINK: '#D147BD', LIGHT_PINK: '#DC75CD', ORANGE: '#FF862F',
  PURE_RED: '#FF0000', PURE_GREEN: '#00FF00', PURE_BLUE: '#0000FF',
  // The "median" shades by their short names
  BLUE: '#58C4DD', TEAL: '#5CD0B3', GREEN: '#83C167', YELLOW: '#FFFF00', GOLD: '#F0AC5F',
  RED: '#FC6255', MAROON: '#C55F73', PURPLE: '#9A72AC', GREY: '#888888',
};

// manim also spells grey as gray
for (const [name, hex] of Object.entries({ ...MANIM_COLORS })) {
  if (name.startsWith('GREY')) MANIM_COLORS[name.replace('GREY', 'GRAY')] = hex;
  if (name === 'GREY_BROWN') MANIM_COLORS.GRAY_BROWN = hex;
}

/** The swatches offered, one row per hue from dark to light, then the odd ones. */
export const SWATCH_ROWS: string[][] = [
  ['WHITE', 'GREY_A', 'GREY_B', 'GREY', 'GREY_D', 'GREY_E', 'BLACK'],
  ['BLUE_E', 'BLUE_D', 'BLUE', 'BLUE_B', 'BLUE_A'],
  ['TEAL_E', 'TEAL_D', 'TEAL', 'TEAL_B', 'TEAL_A'],
  ['GREEN_E', 'GREEN_D', 'GREEN', 'GREEN_B', 'GREEN_A'],
  ['YELLOW_E', 'YELLOW_D', 'YELLOW', 'YELLOW_B', 'YELLOW_A'],
  ['GOLD_E', 'GOLD_D', 'GOLD', 'GOLD_B', 'GOLD_A'],
  ['RED_E', 'RED_D', 'RED', 'RED_B', 'RED_A'],
  ['MAROON_E', 'MAROON_D', 'MAROON', 'MAROON_B', 'MAROON_A'],
  ['PURPLE_E', 'PURPLE_D', 'PURPLE', 'PURPLE_B', 'PURPLE_A'],
  ['PINK', 'LIGHT_PINK', 'ORANGE', 'LIGHT_BROWN', 'DARK_BROWN', 'GREY_BROWN'],
];

const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

export function isHexColor(value: string): boolean {
  return HEX.test(value);
}

/** Whether a scene file would accept this as a color. */
export function isColor(value: string): boolean {
  return isHexColor(value) || value.toUpperCase() in MANIM_COLORS;
}

/** The hex a color value stands for, for drawing it; null when it isn't a color. */
export function colorToHex(value: string | null | undefined): string | null {
  if (!value) return null;
  if (isHexColor(value)) {
    if (value.length === 4) return `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`.toUpperCase();
    return value.slice(0, 7).toUpperCase();
  }
  return MANIM_COLORS[value.toUpperCase()] ?? null;
}

/**
 * How a typed color is written into the file: names in upper case, as the format keeps
 * them; hex as typed. Returns null for something which isn't a color.
 */
export function normalizeColor(value: string): string | null {
  const trimmed = value.trim();
  if (isHexColor(trimmed)) return trimmed;
  const upper = trimmed.toUpperCase().replace(/\s+/g, '_');
  return upper in MANIM_COLORS ? upper : null;
}

/** "BLUE_E" -> "Blue E", for tooltips. */
export function colorLabel(name: string): string {
  return name.split('_').map((w) => w.charAt(0) + w.slice(1).toLowerCase()).join(' ');
}

/** Black or white, whichever reads better on the given color. */
export function contrastText(hex: string): string {
  const full = colorToHex(hex) ?? '#000000';
  const r = parseInt(full.slice(1, 3), 16);
  const g = parseInt(full.slice(3, 5), 16);
  const b = parseInt(full.slice(5, 7), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#000000' : '#FFFFFF';
}
