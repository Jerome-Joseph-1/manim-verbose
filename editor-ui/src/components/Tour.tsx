/**
 * A short tour for someone opening the editor for the first time: four stops, each pointing
 * at the control it is about (add an object, add a step, preview, export). It can be skipped
 * at any point, and once finished or skipped it doesn't come back, which the browser
 * remembers (localStorage); the shortcuts list has a way to take it again.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useEditor } from '../state/store';
import { Icon } from './Icon';

export const TOUR_KEY = 'manim-editor-tour';

export interface TourStop {
  /** CSS selector of the control the stop is about. */
  anchor: string;
  title: string;
  text: string;
}

export const TOUR: TourStop[] = [
  {
    anchor: '[data-testid="add-object"]',
    title: 'Add an object',
    text: 'Objects are the things in your video: text, equations, shapes, graphs. Add one here; it appears in the list, and on the picture once a step shows it.',
  },
  {
    anchor: '[data-testid="add-step"]',
    title: 'Add a step',
    text: 'Steps play one after another: show an object, move it, change it, transform it into another. The picture shows the moment after the selected step.',
  },
  {
    anchor: '[data-tour="preview"]',
    title: 'Preview',
    text: 'Play the selected step, or the whole scene, as a short video to see how it moves.',
  },
  {
    anchor: '[data-tour="export"]',
    title: 'Export',
    text: 'When it looks right, make the finished video, an MP4 to download. Everything you do is saved as you go.',
  },
];

function tourDone(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === 'done';
  } catch {
    return true; // nowhere to remember it: don't show it every time
  }
}

/** Start the tour if this browser hasn't seen it. */
export function maybeStartTour(): void {
  if (tourDone()) return;
  // A moment later, once the page has laid out
  setTimeout(() => {
    const state = useEditor.getState();
    if (state.status === 'ready' && state.tourStep === null) useEditor.setState({ tourStep: 0 });
  }, 400);
}

export function startTour(): void {
  useEditor.setState({ tourStep: 0, modal: null });
}

export function endTour(): void {
  try {
    localStorage.setItem(TOUR_KEY, 'done');
  } catch {
    // not remembered, which is fine
  }
  useEditor.setState({ tourStep: null });
}

interface Placement {
  top: number;
  left: number;
  ring: { top: number; left: number; width: number; height: number } | null;
  arrow: 'up' | 'down' | null;
}

const WIDTH = 320;
const GAP = 12;

function placeFor(anchor: Element | null, height: number): Placement {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!anchor) return { top: vh / 2 - height / 2, left: vw / 2 - WIDTH / 2, ring: null, arrow: null };
  const r = anchor.getBoundingClientRect();
  const below = r.bottom + GAP + height <= vh - 8;
  const top = below ? r.bottom + GAP : Math.max(8, r.top - GAP - height);
  const left = Math.max(8, Math.min(vw - WIDTH - 8, r.left + r.width / 2 - WIDTH / 2));
  return { top, left, ring: { top: r.top - 4, left: r.left - 4, width: r.width + 8, height: r.height + 8 }, arrow: below ? 'up' : 'down' };
}

export function Tour() {
  const step = useEditor((s) => s.tourStep);
  const modal = useEditor((s) => s.modal);
  const confirm = useEditor((s) => s.confirm);
  if (step === null || modal !== null || confirm !== null) return null;
  const stop = TOUR[step];
  if (!stop) return null;
  return <TourPopover index={step} stop={stop} />;
}

function TourPopover({ index, stop }: { index: number; stop: TourStop }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [place, setPlace] = useState<Placement | null>(null);
  const last = index === TOUR.length - 1;

  useLayoutEffect(() => {
    const measure = () => setPlace(placeFor(document.querySelector(stop.anchor), ref.current?.offsetHeight ?? 180));
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [stop]);

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus({ preventScroll: true });
  }, [index]);

  const go = (to: number) => useEditor.setState({ tourStep: to });
  return (
    <>
      {place?.ring ? <div className="tour-ring" style={place.ring} aria-hidden="true" /> : null}
      <div
        ref={ref}
        className={`tour${place?.arrow ? ` arrow-${place.arrow}` : ''}`}
        style={{ top: place?.top ?? -9999, left: place?.left ?? -9999, width: WIDTH }}
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        data-testid="tour"
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            endTour();
          }
        }}
      >
        <div className="tour-head">
          <span className="tour-count">
            {index + 1} of {TOUR.length}
          </span>
          <button type="button" className="icon-btn" aria-label="Close the tour" onClick={endTour}>
            <Icon name="x" />
          </button>
        </div>
        <h2 id={titleId}>{stop.title}</h2>
        <p>{stop.text}</p>
        <div className="tour-foot">
          <button type="button" className="btn btn-sm btn-ghost" onClick={endTour}>
            Skip the tour
          </button>
          <span className="push" />
          {index > 0 ? (
            <button type="button" className="btn btn-sm" onClick={() => go(index - 1)}>
              Back
            </button>
          ) : null}
          <button type="button" className="btn btn-sm btn-primary" data-autofocus onClick={() => (last ? endTour() : go(index + 1))}>
            {last ? 'Done' : 'Next'}
          </button>
        </div>
      </div>
    </>
  );
}
