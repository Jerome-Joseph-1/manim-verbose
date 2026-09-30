/**
 * What the canvas draws over the selected object for changing it by hand: a handle on each
 * point that can be moved on its own (a vector's tip, a line's ends, a polygon's corners),
 * the outline of its points while it is dragged, and for an object placed as a whole a
 * corner handle to resize it and one above it to turn it. All in pixels of the canvas as
 * displayed; the handles carry data-handle attributes the canvas reads on pointerdown.
 */
import type { SceneObject } from '../doc/types';
import type { Space, Vec2 } from '../lib/coords';
import { allPoints, pointHandles, pointOf, type HandleRef } from '../lib/handles';

export type Gesture =
  | { kind: 'body'; id: string; pointerId: number; startX: number; startY: number; dx: number; dy: number; moved: boolean; draggable: boolean; coarse: boolean }
  | { kind: 'point'; id: string; pointerId: number; handle: HandleRef; startX: number; startY: number; dx: number; dy: number; moved: boolean; coarse: boolean }
  | ({ kind: 'scale' } & TurnOrResize)
  | ({ kind: 'rotate' } & TurnOrResize);

interface TurnOrResize {
  id: string;
  pointerId: number;
  center: Vec2;
  from: Vec2;
  to: Vec2;
  start: number;
  moved: boolean;
  coarse: boolean;
}

export const ROTATE_HANDLE_GAP = 38;

interface Props {
  obj: SceneObject;
  /** The object's box on the canvas as displayed: x0, y0, x1, y1. */
  box: [number, number, number, number];
  /** The object's own units, or null when its coordinate system isn't in the picture. */
  space: Space | null;
  /** Still pixels to displayed pixels. */
  scale: number;
  gesture: Gesture | null;
  /** Placed as a whole, so it can be resized and turned. */
  placed: boolean;
  /** The new scale or rotation while a handle is dragged, for the preview. */
  preview: { scale?: number; startScale?: number; rotate?: number; startRotate?: number };
}

function arcPoints(obj: SceneObject, space: Space): number[][] {
  const center = pointOf(obj, { field: 'center' }) ?? [0, 0];
  const radius = typeof obj.radius === 'number' ? obj.radius : 1;
  const start = typeof obj.start_angle === 'number' ? obj.start_angle : 0;
  const end = typeof obj.end_angle === 'number' ? obj.end_angle : 90;
  void space;
  const out: number[][] = [];
  const steps = 24;
  for (let i = 0; i <= steps; i += 1) {
    const t = ((start + ((end - start) * i) / steps) * Math.PI) / 180;
    out.push([center[0]! + radius * Math.cos(t), center[1]! + radius * Math.sin(t)]);
  }
  return out;
}

export function CanvasHandles({ obj, box, space, scale, gesture, placed, preview }: Props) {
  const mine = gesture && gesture.id === obj.id ? gesture : null;
  const parts: React.ReactNode[] = [];

  if (space) {
    const toDisplay = (p: readonly number[]): Vec2 => {
      const [x, y] = space.toPixel(p);
      return [x * scale, y * scale];
    };
    // Where each point is now, following a drag in progress
    const bodyOffset: Vec2 = mine?.kind === 'body' && mine.moved && mine.draggable ? [mine.dx, mine.dy] : [0, 0];
    const pointMove = mine?.kind === 'point' && mine.moved ? mine : null;
    const place = (p: readonly number[], handle?: Pick<HandleRef, 'field' | 'index'>): Vec2 => {
      const [x, y] = toDisplay(p);
      if (pointMove && handle && pointMove.handle.field === handle.field && pointMove.handle.index === handle.index) {
        return [x + pointMove.dx, y + pointMove.dy];
      }
      return [x + bodyOffset[0], y + bodyOffset[1]];
    };
    const outline = outlineOf(obj, space, place);
    if (outline) parts.push(outline);
    for (const handle of pointHandles(obj)) {
      const p = pointOf(obj, handle);
      if (!p) continue;
      const [x, y] = place(p, handle);
      const active = pointMove?.handle.field === handle.field && pointMove.handle.index === handle.index;
      parts.push(
        <circle
          key={`h-${handle.field}-${handle.index ?? ''}`}
          className={`handle point-handle${active ? ' active' : ''}`}
          cx={x}
          cy={y}
          r={handle.field === 'tip' || handle.field === 'end' ? 7 : 6}
          data-handle="point"
          data-field={handle.field}
          data-index={handle.index ?? undefined}
          data-testid={`handle-${handle.field}${handle.index !== undefined ? `-${handle.index}` : ''}`}
        >
          <title>{`Drag to move the ${handle.label}`}</title>
        </circle>,
      );
    }
  }

  if (placed) {
    const [x0, y0, x1, y1] = box;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const scaling = mine?.kind === 'scale' && mine.moved;
    const turning = mine?.kind === 'rotate' && mine.moved;
    const factor = scaling && preview.scale && preview.startScale ? preview.scale / preview.startScale : 1;
    const hw = ((x1 - x0) / 2) * factor;
    const hh = ((y1 - y0) / 2) * factor;
    const angle = turning ? -((preview.rotate ?? 0) - (preview.startRotate ?? 0)) : 0;
    if (scaling || turning) {
      parts.push(
        <rect
          key="preview"
          className="transform-preview"
          x={cx - hw}
          y={cy - hh}
          width={hw * 2}
          height={hh * 2}
          transform={angle ? `rotate(${angle} ${cx} ${cy})` : undefined}
        />,
      );
    }
    const rx = cx;
    const ry = cy - hh - ROTATE_HANDLE_GAP;
    parts.push(
      <g key="rotate" transform={angle ? `rotate(${angle} ${cx} ${cy})` : undefined}>
        <line className="rotate-stem" x1={cx} y1={cy - hh - 22} x2={rx} y2={ry} />
        <circle className={`handle rotate-handle${turning ? ' active' : ''}`} cx={rx} cy={ry} r={7} data-handle="rotate" data-testid="handle-rotate">
          <title>Drag to turn it (Shift: in steps of 15°)</title>
        </circle>
      </g>,
    );
    parts.push(
      <rect
        key="scale"
        className={`handle scale-handle${scaling ? ' active' : ''}`}
        x={cx + hw - 6}
        y={cy + hh - 6}
        width={12}
        height={12}
        rx={2}
        data-handle="scale"
        data-testid="handle-scale"
      >
        <title>Drag to resize it (Shift: in steps of a quarter)</title>
      </rect>,
    );
  }

  if (parts.length === 0) return null;
  return (
    <svg className="canvas-handles" aria-hidden="true" data-testid="canvas-handles">
      <defs>
        <marker id="handle-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" className="outline-arrow" />
        </marker>
      </defs>
      {parts}
    </svg>
  );
}

/** The object's points joined up the way it is drawn: a vector's shaft, a polygon's sides. */
function outlineOf(obj: SceneObject, space: Space, place: (p: readonly number[], handle?: Pick<HandleRef, 'field' | 'index'>) => Vec2): React.ReactNode {
  const join = (points: Vec2[]) => points.map(([x, y]) => `${x},${y}`).join(' ');
  switch (obj.type) {
    case 'vector': {
      const tail = pointOf(obj, { field: 'tail' });
      const tip = pointOf(obj, { field: 'tip' });
      if (!tail || !tip) return null;
      const [a, b] = [place(tail, { field: 'tail' }), place(tip, { field: 'tip' })];
      return <line key="outline" className="outline" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} markerEnd="url(#handle-arrow)" />;
    }
    case 'line':
    case 'brace': {
      const start = pointOf(obj, { field: 'start' });
      const end = pointOf(obj, { field: 'end' });
      if (!start || !end) return null;
      const [a, b] = [place(start, { field: 'start' }), place(end, { field: 'end' })];
      return <line key="outline" className="outline" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />;
    }
    case 'polygon': {
      const points = Array.isArray(obj.points) ? (obj.points as number[][]) : [];
      return <polygon key="outline" className="outline" points={join(points.map((p, index) => place(p, { field: 'points', index })))} />;
    }
    case 'angle':
      return <polyline key="outline" className="outline" points={join(allPoints(obj).map((p) => place(p)))} />;
    case 'arc':
      return <polyline key="outline" className="outline" points={join(arcPoints(obj, space).map((p) => place(p)))} />;
    case 'dot': {
      const p = pointOf(obj, { field: 'point' });
      if (!p) return null;
      const [x, y] = place(p);
      return <circle key="outline" className="outline" cx={x} cy={y} r={4} />;
    }
    default:
      return null;
  }
}
