/** A button opening a list of choices, usable with the keyboard alone. */
import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';

export interface MenuEntry {
  key: string;
  label: string;
  description?: string;
  icon?: string;
  heading?: string;
  onSelect: () => void;
}

export function Menu({
  label, buttonLabel, entries, align = 'right', buttonClass = 'btn btn-sm', testId, icon = 'plus',
}: {
  label: string;
  buttonLabel: React.ReactNode;
  entries: MenuEntry[];
  align?: 'left' | 'right';
  buttonClass?: string;
  testId?: string;
  icon?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const close = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    requestAnimationFrame(() => root.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus());
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const items = () => [...(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];

  return (
    <div className="menu-anchor" ref={root}>
      <button
        ref={button}
        type="button"
        className={buttonClass}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        data-testid={testId}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name={icon} /> {buttonLabel}
      </button>
      {open ? (
        <div
          className={`menu ${align}`}
          role="menu"
          id={menuId}
          aria-label={label}
          onKeyDown={(e) => {
            const list = items();
            const at = list.indexOf(document.activeElement as HTMLElement);
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              list[(at + 1) % list.length]?.focus();
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              list[(at - 1 + list.length) % list.length]?.focus();
            } else if (e.key === 'Home') {
              e.preventDefault();
              list[0]?.focus();
            } else if (e.key === 'End') {
              e.preventDefault();
              list.at(-1)?.focus();
            } else if (e.key === 'Escape' || e.key === 'Tab') {
              if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
              }
              setOpen(false);
              button.current?.focus();
            }
          }}
        >
          {entries.map((entry) => (
            <div key={entry.key} role="none">
              {entry.heading ? (
                <div className="menu-heading" role="presentation">
                  {entry.heading}
                </div>
              ) : null}
              <button
                type="button"
                role="menuitem"
                className="menu-item"
                tabIndex={-1}
                data-key={entry.key}
                onClick={() => {
                  setOpen(false);
                  entry.onSelect();
                }}
              >
                <span className="title">
                  {entry.icon ? <Icon name={entry.icon} /> : null}
                  {entry.label}
                </span>
                {entry.description ? <span className="desc">{entry.description}</span> : null}
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
