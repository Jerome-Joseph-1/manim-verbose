/**
 * The picture: the frame after the selected step, with a box over each object on screen.
 * Hover shows what is where, a click selects the topmost object (click again for the one
 * underneath), and dragging moves it: an object placed as a whole to a new place, an object
 * given by points (a dot, a vector, a polygon) by moving its points, in the units they are
 * written in, which for an object on a number plane are the plane's coordinates. The selected
 * object has handles: its points' own (a vector's tip), and for one placed as a whole, one to
 * resize it and one to turn it.
 *
 * From the keyboard: Tab and Shift+Tab go through the objects in the picture, Enter selects
 * one, the arrow keys move the selected one (see shortcuts.ts).
 *
 * A picture file dropped on it is uploaded and added where it was dropped.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { findObject, findScene } from '../doc/ops';
import { neverShown } from '../doc/screen';
import { storage } from '../doc/storage';
import type { Placement, Scene, SceneObject } from '../doc/types';
import { snap, spaceFor, systemSpace, tidy, type Space, type Vec2 } from '../lib/coords';
import { boxCenter, cycleHit, hitTest, pixelDeltaToFrame, pixelToFrame, type Box, type StillObject } from '../lib/geometry';
import { isPlotted, pointOf } from '../lib/handles';
import { hasPlacement, objectKind, stepKind } from '../lib/schema';
import { rotationFromDrag, scaleFromDrag } from '../lib/transform';
import { ApiError } from '../lib/api';
import { currentSceneId, frameStepIndex, select, toast, useEditor } from '../state/store';
import {
  addObjectFrom, addPictureObject, isBlankDocument, moveOnSystem, movePointTo, placeObjectAt, setScaleAndRotation, showObjects, stepFrame,
  translatePoints,
} from '../state/actions';
import { stepSummary, useCatalog } from './Sidebar';
import { CanvasHandles, type Gesture } from './CanvasHandles';
import { Icon } from './Icon';
import { TemplateStrip } from './TemplateGallery';
import { useStill, type StillView } from './useStill';

const PADDING = 32;
const WIDTH_STEP = 160;
const PICTURE_TYPES = /^image\/(png|jpeg|gif|webp|svg\+xml)$/;
const PICTURE_NAMES = /\.(png|jpe?g|gif|webp|svg)$/i;

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

function placementOf(obj: SceneObject): Placement | null {
  const place = obj.place;
  return place && typeof place === 'object' && !Array.isArray(place) ? (place as Placement) : null;
}

/** Objects in reading order (top to bottom, then left to right), for going through them with Tab. */
function readingOrder(objects: StillObject[]): StillObject[] {
  return [...objects].sort((a, b) => {
    const ay = Math.min(a.bbox[1], a.bbox[3]);
    const by = Math.min(b.bbox[1], b.bbox[3]);
    if (Math.abs(ay - by) > 8) return ay - by;
    return Math.min(a.bbox[0], a.bbox[2]) - Math.min(b.bbox[0], b.bbox[2]);
  });
}

function fmt(value: number): string {
  return String(tidy(Math.round(value * 100) / 100));
}

export function Canvas() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const schema = useEditor((s) => s.schema);
  const sceneId = useEditor((s) => currentSceneId(s));
  const selection = useEditor((s) => s.selection);
  const stepIndex = useEditor((s) => (sceneId ? frameStepIndex(s, sceneId) : -1));
  const layoutProblems = useEditor((s) => (sceneId ? s.layoutProblems[sceneId] : undefined));
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
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const [keyboardAt, setKeyboardAt] = useState<number | null>(null);
  const [dropping, setDropping] = useState<'over' | 'uploading' | null>(null);
  const lastClick = useRef<{ x: number; y: number } | null>(null);
  const overlay = useRef<HTMLDivElement>(null);

  const selectedId = selection.kind === 'object' && selection.sceneId === sceneId ? selection.id : null;
  const scale = shown ? display.width / shown.width : 1;
  const objects = useMemo(() => still?.objects ?? [], [still]);
  const ordered = useMemo(() => readingOrder(objects), [objects]);
  const keyboardId = keyboardAt !== null ? (ordered[keyboardAt]?.id ?? null) : null;
  const warnings = useMemo(() => {
    const out = new Map<string, string[]>();
    for (const p of layoutProblems ?? []) {
      if (!p.item_id) continue;
      out.set(p.item_id, [...(out.get(p.item_id) ?? []), p.message]);
    }
    return out;
  }, [layoutProblems]);

  // Clear a hover or keyboard spot left from a picture no longer shown
  useEffect(() => {
    if (hover && !objects.some((o) => o.id === hover)) setHover(null);
    if (keyboardAt !== null && keyboardAt >= ordered.length) setKeyboardAt(null);
  }, [objects, ordered, hover, keyboardAt]);

  if (!doc || !schema || !scene || !sceneId) return <div className="canvas-wrap" ref={wrap} />;

  const local = (event: { clientX: number; clientY: number }): Vec2 => {
    const rect = overlay.current!.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };

  const spaceOf = (obj: SceneObject, view: StillView): Space | null => spaceFor(obj.on, view.mapping, view.systems);

  const isDraggable = (id: string): boolean => {
    const obj = findObject(doc, sceneId, id);
    if (!obj || !still) return false;
    if (hasPlacement(schema, obj.type)) return true;
    return isPlotted(obj) && spaceOf(obj, still) !== null;
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0 || !still) return;
    const [lx, ly] = local(event);
    const handle = (event.target as Element).closest?.('[data-handle]');
    if (handle && selectedId) {
      const obj = findObject(doc, sceneId, selectedId);
      const box = objects.find((o) => o.id === selectedId);
      if (obj && box) {
        overlay.current?.setPointerCapture?.(event.pointerId);
        const kind = handle.getAttribute('data-handle');
        if (kind === 'point') {
          const index = handle.getAttribute('data-index');
          const field = handle.getAttribute('data-field') ?? '';
          setGesture({
            kind: 'point', id: selectedId, pointerId: event.pointerId, handle: { field, index: index === null ? undefined : Number(index), label: field },
            startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, moved: false, coarse: event.shiftKey,
          });
        } else if (kind === 'scale' || kind === 'rotate') {
          const [cx, cy] = boxCenter(box.bbox);
          const start = kind === 'scale' ? (typeof obj.scale === 'number' ? obj.scale : 1) : typeof obj.rotate === 'number' ? obj.rotate : 0;
          setGesture({ kind, id: selectedId, pointerId: event.pointerId, center: [cx * scale, cy * scale], from: [lx, ly], to: [lx, ly], start, moved: false, coarse: event.shiftKey });
        }
        event.preventDefault();
        return;
      }
    }
    setKeyboardAt(null);
    const [x, y] = [lx / scale, ly / scale];
    const same = lastClick.current && Math.hypot(lastClick.current.x - x, lastClick.current.y - y) < 4;
    lastClick.current = { x, y };
    const hit: StillObject | null = same ? cycleHit(objects, x, y, selectedId) : hitTest(objects, x, y);
    if (!hit) {
      select({ kind: 'scene', sceneId, id: null });
      return;
    }
    select({ kind: 'object', sceneId, id: hit.id });
    overlay.current?.setPointerCapture?.(event.pointerId);
    setGesture({
      kind: 'body', id: hit.id, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, dx: 0, dy: 0, moved: false,
      draggable: isDraggable(hit.id), coarse: event.shiftKey,
    });
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (gesture && gesture.pointerId === event.pointerId) {
      if (gesture.kind === 'body' || gesture.kind === 'point') {
        const dx = event.clientX - gesture.startX;
        const dy = event.clientY - gesture.startY;
        setGesture({ ...gesture, dx, dy, moved: gesture.moved || Math.hypot(dx, dy) > 3, coarse: event.shiftKey });
      } else {
        const to = local(event);
        setGesture({ ...gesture, to, moved: gesture.moved || Math.hypot(to[0] - gesture.from[0], to[1] - gesture.from[1]) > 2, coarse: event.shiftKey });
      }
      return;
    }
    if (!still) return;
    const [x, y] = local(event);
    const hit = hitTest(objects, x / scale, y / scale);
    setHover(hit?.id ?? null);
  };

  const finish = (current: Gesture) => {
    if (!still || !current.moved) return;
    const obj = findObject(doc, sceneId, current.id);
    if (!obj) return;
    if (current.kind === 'scale') {
      setScaleAndRotation(sceneId, obj.id, { scale: scaleFromDrag(current.start, current.center, current.from, current.to, current.coarse) });
      return;
    }
    if (current.kind === 'rotate') {
      setScaleAndRotation(sceneId, obj.id, { rotate: rotationFromDrag(current.start, current.center, current.from, current.to, current.coarse) });
      return;
    }
    // Screen pixels -> still pixels
    const px = current.dx / scale;
    const py = current.dy / scale;
    if (current.kind === 'point') {
      const space = spaceOf(obj, still);
      const old = pointOf(obj, current.handle);
      if (!space || !old) return;
      const [du, dv] = space.fromPixelDelta(px, py);
      movePointTo(sceneId, obj.id, current.handle, [old[0]! + du, old[1]! + dv], current.coarse ? space.bigStep : space.step);
      return;
    }
    if (!current.draggable) return;
    if (hasPlacement(schema, obj.type)) {
      const place = placementOf(obj);
      const system = place && Array.isArray(place.at) && typeof place.on === 'string' ? still.systems.find((s) => s.id === place.on) : undefined;
      if (system) {
        // Keep it on its coordinate system, in its coordinates
        const space = systemSpace(system);
        moveOnSystem(sceneId, obj.id, space.fromPixelDelta(px, py), current.coarse ? space.bigStep : space.step);
        return;
      }
      const box = objects.find((o) => o.id === current.id);
      if (!box) return;
      const [fdx, fdy] = pixelDeltaToFrame(still.mapping, px, py);
      const [cx, cy] = boxCenter(box.frame_bbox);
      const at: [number, number] = [cx + fdx, cy + fdy];
      if (current.coarse) placeObjectAt(sceneId, obj.id, [Math.round(at[0] * 2) / 2, Math.round(at[1] * 2) / 2]);
      else placeObjectAt(sceneId, obj.id, at);
      return;
    }
    const space = spaceOf(obj, still);
    if (!space) return;
    const [du, dv] = space.fromPixelDelta(px, py);
    translatePoints(sceneId, obj.id, du, dv, undefined, current.coarse ? space.bigStep : space.step);
  };

  const onPointerUp = (event: React.PointerEvent) => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    overlay.current?.releasePointerCapture?.(event.pointerId);
    const current = gesture;
    setGesture(null);
    finish(current);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Tab') {
      const count = ordered.length;
      if (count === 0) return;
      const next = keyboardAt === null ? (event.shiftKey ? count - 1 : 0) : keyboardAt + (event.shiftKey ? -1 : 1);
      if (next < 0 || next >= count) {
        // Past the first or last object: let focus leave the picture as usual
        setKeyboardAt(null);
        return;
      }
      event.preventDefault();
      setKeyboardAt(next);
    } else if ((event.key === 'Enter' || event.key === ' ') && keyboardId) {
      event.preventDefault();
      select({ kind: 'object', sceneId, id: keyboardId });
    } else if (event.key === 'Escape' && keyboardAt !== null) {
      event.preventDefault();
      setKeyboardAt(null);
    }
  };

  // Pictures dropped from the computer
  const hasFiles = (event: React.DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes('Files');
  const onDragOver = (event: React.DragEvent) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = storage().uploadAsset ? 'copy' : 'none';
    if (dropping !== 'over' && dropping !== 'uploading') setDropping('over');
  };
  const onDrop = async (event: React.DragEvent) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    const file = Array.from(event.dataTransfer.files ?? [])[0];
    const upload = storage().uploadAsset;
    if (!file) {
      setDropping(null);
      return;
    }
    if (!upload) {
      setDropping(null);
      toast("Pictures can't be added here: this editor has nowhere to keep them", 'error');
      return;
    }
    if (!PICTURE_TYPES.test(file.type) && !PICTURE_NAMES.test(file.name)) {
      setDropping(null);
      toast(`${file.name} isn't a picture: drop a PNG, JPEG, GIF, WebP or SVG file`, 'error');
      return;
    }
    let at: [number, number] | undefined;
    if (still && overlay.current) {
      const [lx, ly] = local(event);
      at = pixelToFrame(still.mapping, lx / scale, ly / scale);
    }
    setDropping('uploading');
    try {
      const { path } = await upload(file, file.name);
      addPictureObject(path, at);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : `${file.name} couldn't be added`, 'error');
    } finally {
      setDropping(null);
    }
  };

  const neverOnScreen = neverShown(scene);
  const step = stepIndex >= 0 ? scene.steps?.[stepIndex] : undefined;
  const steps = scene.steps ?? [];
  const selectedObj = selectedId ? findObject(doc, sceneId, selectedId) : undefined;
  const selectedBox = selectedId ? objects.find((o) => o.id === selectedId) : undefined;
  const bodyMoving = gesture?.kind === 'body' && gesture.moved;
  const keyboardObj = keyboardId ? (findObject(doc, sceneId, keyboardId) ?? null) : null;
  const preview = gesturePreview(gesture);
  const readout = still && gesture?.moved ? readoutFor(gesture, doc && findObject(doc, sceneId, gesture.id), still, scale, objects) : null;

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
      <div
        className={`canvas-wrap${dropping ? ' dropping' : ''}`}
        ref={wrap}
        onDragOver={onDragOver}
        onDragLeave={(e) => {
          if (dropping === 'over' && !(e.currentTarget as Node).contains(e.relatedTarget as Node | null)) setDropping(null);
        }}
        onDrop={(e) => void onDrop(e)}
      >
        {display.width > 0 ? (
          <div
            className="canvas"
            style={{ width: display.width, height: display.height }}
            data-testid="canvas"
            role="group"
            aria-roledescription="picture"
            aria-label={`Picture of scene ${scene.title || scene.id} ${step ? `after step ${stepIndex + 1}` : 'at its start'}${selectedId ? `, ${selectedId} selected` : ''}. Tab goes through the objects in it, Enter selects one, arrow keys move the selected one.`}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onBlur={() => setKeyboardAt(null)}
          >
            {shown ? <img src={shown.url} alt="" draggable={false} data-testid="still" /> : <div className="canvas-placeholder" />}
            <div
              className="canvas-overlay"
              ref={overlay}
              data-testid="canvas-overlay"
              style={{ cursor: gestureCursor(gesture, hover) }}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={() => setGesture(null)}
              onPointerLeave={() => setHover(null)}
            >
              {still
                ? objects.map((obj) => (
                    <ObjectBox
                      key={obj.id}
                      obj={obj}
                      scale={scale}
                      hover={hover === obj.id && selectedId !== obj.id && !gesture}
                      selected={selectedId === obj.id}
                      keyboard={keyboardId === obj.id}
                      warnings={warnings.get(obj.id)}
                      offset={gesture?.kind === 'body' && gesture.moved && gesture.draggable && gesture.id === obj.id ? [gesture.dx, gesture.dy] : null}
                    />
                  ))
                : null}
              {still && selectedObj && selectedBox ? (
                <CanvasHandles
                  obj={selectedObj}
                  box={[selectedBox.bbox[0] * scale, selectedBox.bbox[1] * scale, selectedBox.bbox[2] * scale, selectedBox.bbox[3] * scale]}
                  space={isPlotted(selectedObj) ? spaceOf(selectedObj, still) : null}
                  scale={scale}
                  gesture={gesture}
                  placed={hasPlacement(schema, selectedObj.type) && !bodyMoving}
                  preview={preview}
                />
              ) : null}
              {readout ? (
                <div
                  className="drag-readout"
                  style={{ left: Math.max(4, Math.min(readout.x, display.width - 170)), top: Math.max(4, Math.min(readout.y, display.height - 26)) }}
                  data-testid="drag-readout"
                >
                  {readout.text}
                </div>
              ) : null}
            </div>
            <div className="sr-only" aria-live="polite" data-testid="canvas-announce">
              {keyboardId
                ? `${keyboardId}${keyboardObj ? `, ${objectKind(schema, keyboardObj.type)?.label ?? keyboardObj.type}` : ''}, ${(keyboardAt ?? 0) + 1} of ${ordered.length}. Enter selects it.`
                : ''}
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
            {(scene.objects ?? []).length === 0 && !(scene.carry ?? []).length ? <EmptyScene blank={isBlankDocument(doc)} /> : null}
            {dropping ? (
              <div className="drop-hint" data-testid="drop-hint">
                {dropping === 'uploading' ? (
                  <>
                    <span className="spinner" /> Adding the picture…
                  </>
                ) : (
                  <>
                    <Icon name="image" /> Drop the picture to add it here
                  </>
                )}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {neverOnScreen.length > 0 && (scene.objects ?? []).length > 0 ? <NeverShownNote scene={scene} ids={neverOnScreen} /> : null}
    </div>
  );
}

function gestureCursor(gesture: Gesture | null, hover: string | null): string {
  if (gesture?.moved) {
    if (gesture.kind === 'body') return gesture.draggable ? 'grabbing' : 'not-allowed';
    if (gesture.kind === 'scale') return 'nwse-resize';
    return 'grabbing';
  }
  return hover ? 'pointer' : 'default';
}

function gesturePreview(gesture: Gesture | null) {
  if (!gesture || !gesture.moved) return {};
  if (gesture.kind === 'scale') return { scale: scaleFromDrag(gesture.start, gesture.center, gesture.from, gesture.to, gesture.coarse), startScale: gesture.start };
  if (gesture.kind === 'rotate') return { rotate: rotationFromDrag(gesture.start, gesture.center, gesture.from, gesture.to, gesture.coarse), startRotate: gesture.start };
  return {};
}

/** The numbers a drag will write, shown beside the pointer as it goes. */
function readoutFor(gesture: Gesture, obj: SceneObject | null | undefined, still: StillView, scale: number, boxes: StillObject[]): { x: number; y: number; text: string } | null {
  if (!obj) return null;
  if (gesture.kind === 'scale' || gesture.kind === 'rotate') {
    const value = gesture.kind === 'scale'
      ? `×${scaleFromDrag(gesture.start, gesture.center, gesture.from, gesture.to, gesture.coarse).toFixed(2)}`
      : `${rotationFromDrag(gesture.start, gesture.center, gesture.from, gesture.to, gesture.coarse)}°`;
    return { x: gesture.to[0] + 14, y: gesture.to[1] + 14, text: value };
  }
  const space = spaceFor(obj.on, still.mapping, still.systems);
  const box = boxes.find((b) => b.id === obj.id);
  if (gesture.kind === 'point') {
    const old = pointOf(obj, gesture.handle);
    if (!space || !old) return null;
    const [du, dv] = space.fromPixelDelta(gesture.dx / scale, gesture.dy / scale);
    const [x, y] = space.toPixel(old);
    const step = gesture.coarse ? space.bigStep : space.step;
    return { x: x * scale + gesture.dx + 14, y: y * scale + gesture.dy + 14, text: `${gesture.handle.label} (${fmt(snap(old[0]! + du, step))}, ${fmt(snap(old[1]! + dv, step))})` };
  }
  if (!gesture.draggable || !box) return null;
  const [cx, cy] = boxCenter(box.bbox);
  const x = cx * scale + gesture.dx;
  const y = Math.max(cy, box.bbox[3]) * scale + gesture.dy + 10;
  if (isPlotted(obj) && space) {
    const [du, dv] = space.fromPixelDelta(gesture.dx / scale, gesture.dy / scale);
    const step = gesture.coarse ? space.bigStep : space.step;
    return { x, y, text: `moved by (${fmt(snap(du, step))}, ${fmt(snap(dv, step))})` };
  }
  const [fx, fy] = pixelToFrame(still.mapping, cx + gesture.dx / scale, cy + gesture.dy / scale);
  return { x, y, text: `at (${fmt(fx)}, ${fmt(fy)})` };
}

function ObjectBox({ obj, scale, hover, selected, keyboard, warnings, offset }: { obj: StillObject; scale: number; hover: boolean; selected: boolean; keyboard: boolean; warnings: string[] | undefined; offset: [number, number] | null }) {
  const [x0, y0, x1, y1] = obj.bbox as Box;
  const left = Math.min(x0, x1) * scale + (offset?.[0] ?? 0);
  const top = Math.min(y0, y1) * scale + (offset?.[1] ?? 0);
  const width = Math.max(4, Math.abs(x1 - x0) * scale);
  const height = Math.max(4, Math.abs(y1 - y0) * scale);
  const className = `obj-box${hover ? ' hover' : ''}${selected ? ' selected' : ''}${keyboard ? ' keyboard' : ''}${warnings ? ' warn' : ''}${top < 24 ? ' below' : ''}`;
  return (
    <div
      className={className}
      style={{ left, top, width, height }}
      data-object-id={obj.id}
      data-testid="object-box"
      data-warning={warnings ? warnings.join(' ') : undefined}
      title={warnings ? warnings.join('\n') : undefined}
      aria-hidden="true"
    >
      {hover || selected || keyboard ? <span className="tag">{obj.id}</span> : warnings ? <span className="tag warn-tag">!</span> : null}
    </div>
  );
}

function EmptyScene({ blank }: { blank: boolean }) {
  const catalog = useCatalog();
  const quick = ['text', 'tex', 'circle', 'axes'].map((type) => catalog?.objects.find((o) => o.type === type)).filter((e) => e !== undefined);
  return (
    <div className="canvas-empty" data-testid="empty-scene">
      <h3>{blank ? 'A new video' : 'This scene is empty'}</h3>
      <p>
        {blank ? 'Start from a template below, or from nothing: add' : 'Start by adding something to it:'} text, an equation, a shape. Every object waits off
        screen until a step shows it, so the editor adds that step for you.
      </p>
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
      {blank ? <TemplateStrip /> : null}
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
