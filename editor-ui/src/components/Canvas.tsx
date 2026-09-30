/**
 * The picture: the frame after the selected step, with a box over each object on screen.
 * Hover shows what is where, a click selects the topmost object (click again for the one
 * underneath), and dragging moves it.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { findObject, findScene } from '../doc/ops';
import { neverShown } from '../doc/screen';
import type { Scene } from '../doc/types';
import { boxCenter, cycleHit, hitTest, pixelDeltaToFrame, type Box, type StillObject } from '../lib/geometry';
import { hasPlacement, stepKind } from '../lib/schema';
import { currentSceneId, frameStepIndex, select, useEditor } from '../state/store';
import { addObjectFrom, placeObjectAt, showObjects, stepFrame, translatePoints } from '../state/actions';
import { stepSummary, useCatalog } from './Sidebar';
import { Icon } from './Icon';
import { useStill } from './useStill';

const PADDING = 32;
const WIDTH_STEP = 160;

/** The width to ask for: what is shown, in device pixels, rounded so edits reuse cache entries. */
function requestWidth(displayWidth: number): number {
  const dpr = typeof window !== 'undefined' ? Math.min(2, window.devicePixelRatio || 1) : 1;
  const wanted = Math.max(480, Math.min(1920, displayWidth * dpr));
  return Math.ceil(wanted / WIDTH_STEP) * WIDTH_STEP;
}

function aspectOf(settings: unknown): number {
  const resolution = (settings as { resolution?: unknown } | undefined)?.resolution;
  if (Array.isArray(resolution) && typeof resolution[0] === 'number' && typeof resolution[1] === 'number' && resolution[1] > 0) {
    return resolution[0] / resolution[1];
  }
  return 16 / 9;
}

interface Drag {
  id: string;
  pointerId: number;
  startX: number;
  startY: number;
  dx: number;
  dy: number;
  moved: boolean;
  draggable: boolean;
}

export function Canvas() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const schema = useEditor((s) => s.schema);
  const sceneId = useEditor((s) => currentSceneId(s));
  const selection = useEditor((s) => s.selection);
  const stepIndex = useEditor((s) => (sceneId ? frameStepIndex(s, sceneId) : -1));
  const scene = doc && sceneId ? findScene(doc, sceneId) : undefined;
  const wrap = useRef<HTMLDivElement>(null);
  const [area, setArea] = useState({ width: 0, height: 0 });
  const aspect = aspectOf(doc?.settings);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const measure = () => setArea({ width: el.clientWidth, height: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const display = useMemo(() => {
    const w = Math.max(0, area.width - PADDING);
    const h = Math.max(0, area.height - PADDING);
    if (w === 0 || h === 0) return { width: 0, height: 0 };
    const width = Math.min(w, h * aspect);
    return { width: Math.floor(width), height: Math.floor(width / aspect) };
  }, [area, aspect]);

  const width = display.width ? requestWidth(display.width) : 0;
  const { still, anyStill, loading, error } = useStill(doc, sceneId, stepIndex, width);
  const shown = still ?? anyStill;
  const [hover, setHover] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const lastClick = useRef<{ x: number; y: number } | null>(null);
  const overlay = useRef<HTMLDivElement>(null);

  const selectedId = selection.kind === 'object' && selection.sceneId === sceneId ? selection.id : null;
  const scale = shown ? display.width / shown.width : 1;
  const objects = useMemo(() => still?.objects ?? [], [still]);

  // Clear a hover left from a scene no longer shown
  useEffect(() => {
    if (hover && !objects.some((o) => o.id === hover)) setHover(null);
  }, [objects, hover]);

  if (!doc || !schema || !scene || !sceneId) return <div className="canvas-wrap" ref={wrap} />;

  const toStill = (event: React.PointerEvent): [number, number] => {
    const rect = overlay.current!.getBoundingClientRect();
    return [(event.clientX - rect.left) / scale, (event.clientY - rect.top) / scale];
  };

  const isDraggable = (id: string): boolean => {
    const obj = findObject(doc, sceneId, id);
    if (!obj) return false;
    if (hasPlacement(schema, obj.type)) return true;
    return ['dot', 'vector', 'line', 'polygon'].includes(obj.type) && typeof obj.on !== 'string';
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0 || !still) return;
    const [x, y] = toStill(event);
    const same = lastClick.current && Math.hypot(lastClick.current.x - x, lastClick.current.y - y) < 4;
    lastClick.current = { x, y };
    const hit: StillObject | null = same ? cycleHit(objects, x, y, selectedId) : hitTest(objects, x, y);
    if (!hit) {
      select({ kind: 'scene', sceneId, id: null });
      return;
    }
    select({ kind: 'object', sceneId, id: hit.id });
    overlay.current?.setPointerCapture?.(event.pointerId);
    setDrag({ id: hit.id, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, moved: false, draggable: isDraggable(hit.id) });
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (drag && drag.pointerId === event.pointerId) {
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      const moved = drag.moved || Math.hypot(dx, dy) > 3;
      setDrag({ ...drag, dx, dy, moved });
      return;
    }
    if (!still) return;
    const [x, y] = toStill(event);
    const hit = hitTest(objects, x, y);
    setHover(hit?.id ?? null);
  };

  const onPointerUp = (event: React.PointerEvent) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    overlay.current?.releasePointerCapture?.(event.pointerId);
    const current = drag;
    setDrag(null);
    if (!current.moved || !still) return;
    if (!current.draggable) return;
    const box = objects.find((o) => o.id === current.id);
    if (!box) return;
    // Screen pixels -> still pixels -> frame units
    const [fdx, fdy] = pixelDeltaToFrame(still.mapping, current.dx / scale, current.dy / scale);
    const obj = findObject(doc, sceneId, current.id);
    if (!obj) return;
    if (hasPlacement(schema, obj.type)) {
      const [cx, cy] = boxCenter(box.frame_bbox);
      // A placement `on` a coordinate system is replaced by frame units here
      placeObjectAt(sceneId, current.id, [cx + fdx, cy + fdy]);
    } else {
      translatePoints(sceneId, current.id, fdx, fdy);
    }
  };

  const neverOnScreen = neverShown(scene);
  const step = stepIndex >= 0 ? scene.steps?.[stepIndex] : undefined;
  const steps = scene.steps ?? [];

  return (
    <div className="center-canvas" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div className="canvas-toolbar">
        <button type="button" className="icon-btn" aria-label="Show the frame after the previous step" title="Previous step ([)" disabled={stepIndex < 0} onClick={() => stepFrame(-1)}>
          <Icon name="left" />
        </button>
        <button type="button" className="icon-btn" aria-label="Show the frame after the next step" title="Next step (])" disabled={stepIndex >= steps.length - 1} onClick={() => stepFrame(1)}>
          <Icon name="right" />
        </button>
        <span className="where" data-testid="frame-label">
          {step ? (
            <>
              After step <strong>{stepIndex + 1}</strong> of {steps.length}: {stepKind(schema, step.do)?.label ?? step.do} {stepSummary(schema, step)}
            </>
          ) : (
            <>
              <strong>Start of the scene</strong>, before any step
            </>
          )}
        </span>
      </div>
      <div className="canvas-wrap" ref={wrap}>
        {display.width > 0 ? (
          <div
            className="canvas"
            style={{ width: display.width, height: display.height }}
            data-testid="canvas"
            role="group"
            aria-roledescription="picture"
            aria-label={`Picture of scene ${scene.title || scene.id} ${step ? `after step ${stepIndex + 1}` : 'at its start'}${selectedId ? `, ${selectedId} selected` : ''}. Arrow keys move the selected object.`}
            tabIndex={0}
          >
            {shown ? <img src={shown.url} alt="" draggable={false} data-testid="still" /> : <div className="canvas-placeholder" />}
            <div
              className="canvas-overlay"
              ref={overlay}
              data-testid="canvas-overlay"
              style={{ cursor: drag?.moved ? (drag.draggable ? 'grabbing' : 'not-allowed') : hover ? 'pointer' : 'default' }}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={() => setDrag(null)}
              onPointerLeave={() => setHover(null)}
            >
              {still
                ? objects.map((obj) => (
                    <ObjectBox
                      key={obj.id}
                      obj={obj}
                      scale={scale}
                      hover={hover === obj.id && selectedId !== obj.id}
                      selected={selectedId === obj.id}
                      offset={drag && drag.moved && drag.draggable && drag.id === obj.id ? [drag.dx, drag.dy] : null}
                    />
                  ))
                : null}
            </div>
            <div className={`canvas-spinner${loading ? ' visible' : ''}`} aria-hidden={!loading} data-testid="canvas-loading" data-loading={loading}>
              <span className="spinner" /> Drawing…
            </div>
            {error ? (
              <div className="canvas-message" role="alert" data-testid="canvas-error">
                <Icon name="alert" />
                <div>
                  {error.message}
                  {error.problems[0] ? <div style={{ marginTop: 2, fontWeight: 600 }}>{error.problems[0].message}</div> : null}
                </div>
                <button type="button" className="btn btn-sm" onClick={() => useEditor.setState({ problemsOpen: true })}>
                  Show problems
                </button>
              </div>
            ) : null}
            {(scene.objects ?? []).length === 0 ? <EmptyScene /> : null}
          </div>
        ) : null}
      </div>
      {neverOnScreen.length > 0 && (scene.objects ?? []).length > 0 ? <NeverShownNote scene={scene} ids={neverOnScreen} /> : null}
    </div>
  );
}

function ObjectBox({ obj, scale, hover, selected, offset }: { obj: StillObject; scale: number; hover: boolean; selected: boolean; offset: [number, number] | null }) {
  const [x0, y0, x1, y1] = obj.bbox as Box;
  const left = Math.min(x0, x1) * scale + (offset?.[0] ?? 0);
  const top = Math.min(y0, y1) * scale + (offset?.[1] ?? 0);
  const width = Math.max(4, Math.abs(x1 - x0) * scale);
  const height = Math.max(4, Math.abs(y1 - y0) * scale);
  const className = `obj-box${hover ? ' hover' : ''}${selected ? ' selected' : ''}${top < 24 ? ' below' : ''}`;
  return (
    <div className={className} style={{ left, top, width, height }} data-object-id={obj.id} data-testid="object-box" aria-hidden="true">
      {hover || selected ? <span className="tag">{obj.id}</span> : null}
    </div>
  );
}

function EmptyScene() {
  const catalog = useCatalog();
  const quick = ['text', 'tex', 'circle', 'axes'].map((type) => catalog?.objects.find((o) => o.type === type)).filter((e) => e !== undefined);
  return (
    <div className="canvas-empty" data-testid="empty-scene">
      <h3>This scene is empty</h3>
      <p>Start by adding something to it. Every object waits off screen until a step shows it, so the editor adds that step for you.</p>
      <div className="quick-add">
        {quick.map((entry) => (
          <button
            key={entry.type}
            type="button"
            className="btn"
            onClick={() => {
              const id = addObjectFrom(entry);
              if (id) showObjects([id]);
            }}
          >
            <Icon name="plus" /> {entry.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function NeverShownNote({ scene, ids }: { scene: Scene; ids: string[] }) {
  const list = ids.length <= 3 ? ids.join(', ') : `${ids.slice(0, 3).join(', ')} and ${ids.length - 3} more`;
  return (
    <div className="offscreen-note" data-testid="never-shown">
      <Icon name="eyeOff" />
      <span>
        {ids.length === 1 ? `${list} isn't` : `${list} aren't`} shown by any step yet, so {ids.length === 1 ? "it won't" : "they won't"} appear in the video.
      </span>
      <button type="button" className="btn btn-sm" onClick={() => showObjects(ids)} aria-label={`Add a step showing ${ids.join(', ')} in ${scene.title || scene.id}`}>
        <Icon name="eye" /> Show {ids.length === 1 ? 'it' : 'them'}
      </button>
    </div>
  );
}
