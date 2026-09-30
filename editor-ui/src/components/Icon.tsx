/** A small set of line icons, drawn on a 24 unit grid. */
const PATHS: Record<string, string> = {
  plus: 'M12 5v14M5 12h14',
  x: 'M6 6l12 12M18 6L6 18',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3',
  redo: 'M15 14l5-5-5-5M20 9H10a6 6 0 000 12h3',
  play: 'M7 4l13 8-13 8z',
  download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
  code: 'M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16',
  film: 'M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4',
  sun: 'M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z',
  grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01',
  up: 'M6 15l6-6 6 6',
  down: 'M6 9l6 6 6-6',
  left: 'M15 6l-6 6 6 6',
  right: 'M9 6l6 6-6 6',
  first: 'M17 6l-6 6 6 6M7 6v12',
  last: 'M7 6l6 6-6 6M17 6v12',
  alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
  check: 'M5 12l5 5 9-10',
  keyboard: 'M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10',
  text: 'M5 6V4h14v2M12 4v16M9 20h6',
  sigma: 'M18 5H6l6 7-6 7h12',
  shapes: 'M4 13h7v7H4zM17 4l4 7h-8zM16.5 13.5a3.5 3.5 0 110 7 3.5 3.5 0 010-7z',
  geometry: 'M5 19L19 5M5 19h6M5 19v-6M19 5a1.5 1.5 0 110 .01',
  grid: 'M4 4h16v16H4zM4 12h16M12 4v16M4 8h16M4 16h16M8 4v16M16 4v16',
  annotation: 'M8 4c-2 0-2 2-2 4s-2 4-2 4 2 2 2 4 0 4 2 4M16 4c2 0 2 2 2 4s2 4 2 4-2 2-2 4 0 4-2 4',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9h.01',
  group: 'M3 7h8v8H3zM13 9h8v8h-8z',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 100 6 3 3 0 000-6z',
  eyeOff: 'M3 3l18 18M10.6 5.1A10 10 0 0122 12s-1.2 2.1-3.4 4M6.5 6.6C3.8 8.3 2 12 2 12s4 7 10 7c1.8 0 3.3-.5 4.6-1.2M10 10a3 3 0 004 4',
  steps: 'M4 6h12M4 12h16M4 18h9',
  scene: 'M3 5h18v12H3zM8 21h8M12 17v4',
  settings: 'M12 9a3 3 0 100 6 3 3 0 000-6zM19 12l2-1-1-3-2 .2-1.3-1.3.2-2-3-1-1 2h-1.8l-1-2-3 1 .2 2L6 7.2 4 7 3 10l2 1v2l-2 1 1 3 2-.2 1.3 1.3-.2 2 3 1 1-2h1.8l1 2 3-1-.2-2 1.3-1.3 2 .2 1-3-2-1z',
  help: 'M12 21a9 9 0 110-18 9 9 0 010 18zM9.5 9a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 3.5M12 17h.01',
  move: 'M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3',
  wand: 'M4 20L16 8M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 11l.7 1.3L21 13l-1.3.7L19 15l-.7-1.3L17 13l1.3-.7z',
  clock: 'M12 21a9 9 0 110-18 9 9 0 010 18zM12 7v5l3 2',
  camera: 'M3 8h4l2-3h6l2 3h4v11H3zM12 10a3.5 3.5 0 100 7 3.5 3.5 0 000-7z',
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, title, className }: { name: IconName | string; title?: string; className?: string }) {
  const d = PATHS[name] ?? PATHS.shapes!;
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title ? <title>{title}</title> : null}
      <path d={d} />
    </svg>
  );
}

const CATEGORY_ICONS: Record<string, string> = {
  'Text & math': 'sigma',
  Shapes: 'shapes',
  Geometry: 'geometry',
  Coordinates: 'grid',
  Annotations: 'annotation',
  Media: 'image',
  Layout: 'group',
};

export function categoryIcon(category: string | undefined): string {
  return CATEGORY_ICONS[category ?? ''] ?? 'shapes';
}

const STEP_ICONS: Record<string, string> = {
  show: 'eye',
  hide: 'eyeOff',
  add: 'plus',
  remove: 'x',
  clear: 'trash',
  transform: 'wand',
  change: 'settings',
  move: 'move',
  highlight: 'alert',
  wait: 'clock',
  camera: 'camera',
  apply_matrix: 'grid',
  together: 'layers',
};

export function stepIcon(kind: string): string {
  return STEP_ICONS[kind] ?? 'steps';
}
