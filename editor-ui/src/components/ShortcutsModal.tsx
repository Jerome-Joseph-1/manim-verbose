import { openModal, useEditor } from '../state/store';
import { Dialog } from './Dialog';

const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl';

const SHORTCUTS: [string[], string][] = [
  [[MOD, 'Z'], 'Undo'],
  [[MOD, 'Shift', 'Z'], 'Redo (also Ctrl+Y)'],
  [[MOD, 'S'], 'Save now (it also saves by itself)'],
  [[MOD, 'D'], 'Duplicate what is selected'],
  [['Delete'], 'Delete what is selected'],
  [['←', '↑', '→', '↓'], 'Nudge the selected object (hold Shift for bigger steps)'],
  [['['], 'Show the frame after the previous step'],
  [[']'], 'Show the frame after the next step'],
  [['Esc'], 'Deselect, or close a dialog'],
  [['?'], 'This list'],
];

export function ShortcutsModal() {
  const open = useEditor((s) => s.modal === 'shortcuts');
  if (!open) return null;
  return (
    <Dialog title="Keyboard shortcuts" onClose={() => openModal(null)} testId="shortcuts-dialog">
      <table className="kbd-table">
        <tbody>
          {SHORTCUTS.map(([keys, what]) => (
            <tr key={what}>
              <td style={{ whiteSpace: 'nowrap' }}>
                {keys.map((k, i) => (
                  <span key={k}>
                    {i > 0 && keys.length < 4 ? ' + ' : i > 0 ? ' ' : ''}
                    <kbd>{k}</kbd>
                  </span>
                ))}
              </td>
              <td>{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="field-help" style={{ marginTop: 12 }}>
        On the picture: click an object to select it, click again to pick the one under it, drag to move it. Everything also works with the
        keyboard: Tab moves between the lists, the picture and the properties.
      </p>
    </Dialog>
  );
}
