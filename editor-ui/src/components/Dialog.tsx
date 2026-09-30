/** A modal dialog: focus moves in and stays in until it closes, Escape closes it. */
import { useEffect, useId, useRef } from 'react';
import { Icon } from './Icon';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';

export function Dialog({
  title, onClose, children, footer, wide, initialFocus, testId,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
  /** Selector of the element to focus first; the first focusable one otherwise. */
  initialFocus?: string;
  testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = ref.current;
    const first = (initialFocus && root?.querySelector<HTMLElement>(initialFocus)) || root?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      if (previous && document.contains(previous)) previous.focus();
    };
  }, [initialFocus]);

  return (
    <div
      className="scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeRef.current();
      }}
    >
      <div
        ref={ref}
        className={`dialog${wide ? ' wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            closeRef.current();
            return;
          }
          if (e.key !== 'Tab' || !ref.current) return;
          const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
          if (items.length === 0) return;
          const firstItem = items[0]!;
          const lastItem = items[items.length - 1]!;
          if (e.shiftKey && document.activeElement === firstItem) {
            e.preventDefault();
            lastItem.focus();
          } else if (!e.shiftKey && document.activeElement === lastItem) {
            e.preventDefault();
            firstItem.focus();
          }
        }}
      >
        <div className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => closeRef.current()}>
            <Icon name="x" />
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-foot">{footer}</div> : null}
      </div>
    </div>
  );
}
