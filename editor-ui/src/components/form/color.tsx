/** A color: manim's palette as swatches, or a name or hex code typed in. */
import { useEffect, useRef, useState } from 'react';
import { MANIM_COLORS, SWATCH_ROWS, colorLabel, colorToHex, normalizeColor } from '../../lib/colors';
import { endEditBurst } from '../../state/store';
import { Icon } from '../Icon';
import type { WidgetProps } from './basic';

export function ColorWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, ariaLabel }: WidgetProps & { ariaLabel?: string }) {
  const current = typeof value === 'string' ? value : '';
  const [draft, setDraft] = useState(current);
  const [seen, setSeen] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  if (current !== seen) {
    setSeen(current);
    if (normalizeColor(draft) !== current) {
      setDraft(current);
      setError(null);
    }
  }

  useEffect(() => {
    if (!open) return undefined;
    const close = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const shown = colorToHex(current) ?? (typeof spec.default === 'string' ? colorToHex(spec.default) : null);
  const choose = (name: string | undefined) => {
    onChange(name);
    setDraft(name ?? '');
    setError(null);
    setOpen(false);
  };
  const upper = current.toUpperCase();

  return (
    <div>
    <div className="color-field" ref={root}>
      <button
        type="button"
        className="swatch-btn"
        aria-label={`${ariaLabel ?? spec.label}: pick from manim's colors`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        <span style={{ background: shown ?? 'transparent' }} />
      </button>
      <input
        id={inputId}
        data-field={dataField}
        className={`input mono${invalid || error ? ' invalid' : ''}`}
        type="text"
        value={draft}
        placeholder={typeof spec.default === 'string' ? `${spec.default} (default)` : 'Default'}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        aria-invalid={invalid || error ? true : undefined}
        spellCheck={false}
        onChange={(e) => {
          const text = e.target.value;
          setDraft(text);
          if (text.trim() === '') {
            setError(spec.required ? 'Choose a color' : null);
            if (!spec.required) onChange(undefined, { coalesce: true });
            return;
          }
          const color = normalizeColor(text);
          if (color) {
            setError(null);
            onChange(color, { coalesce: true });
          } else {
            setError('Not a color yet: use a name like BLUE or RED_E, or a hex code like #58C4DD');
          }
        }}
        onBlur={() => {
          if (error) {
            setDraft(current);
            setError(null);
          }
          endEditBurst();
        }}
      />
      {!spec.required && current ? (
        <button type="button" className="icon-btn" aria-label={`Clear ${ariaLabel ?? spec.label}`} title="Back to the default" onClick={() => choose(undefined)}>
          <Icon name="x" />
        </button>
      ) : null}
      {open ? (
        <div
          className="palette"
          role="dialog"
          aria-label="manim colors"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              setOpen(false);
            }
          }}
        >
          {SWATCH_ROWS.map((row) => (
            <div className="palette-row" key={row[0]}>
              {row.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="palette-swatch"
                  style={{ background: MANIM_COLORS[name] }}
                  aria-label={colorLabel(name)}
                  aria-pressed={upper === name}
                  title={name}
                  onMouseEnter={() => setHovered(name)}
                  onFocus={() => setHovered(name)}
                  onClick={() => choose(name)}
                />
              ))}
            </div>
          ))}
          <div className="palette-name">{hovered ? `${hovered} ${MANIM_COLORS[hovered]}` : 'Pick a color, or type a hex code'}</div>
        </div>
      ) : null}
    </div>
      {error ? <div className="local-error" role="alert">{error}</div> : null}
    </div>
  );
}
