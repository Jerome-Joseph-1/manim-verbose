import { closeConfirm, useEditor } from '../state/store';
import { Dialog } from './Dialog';

export function ConfirmDialog() {
  const confirm = useEditor((s) => s.confirm);
  if (!confirm) return null;
  return (
    <Dialog
      title={confirm.title}
      onClose={closeConfirm}
      testId="confirm-dialog"
      initialFocus="[data-autofocus]"
      footer={
        <>
          <button type="button" className="btn left" onClick={closeConfirm}>
            Cancel
          </button>
          {confirm.altLabel && confirm.onAlt ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                closeConfirm();
                confirm.onAlt?.();
              }}
            >
              {confirm.altLabel}
            </button>
          ) : null}
          <button
            type="button"
            data-autofocus
            className={`btn ${confirm.danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={() => {
              closeConfirm();
              confirm.onConfirm();
            }}
          >
            {confirm.confirmLabel}
          </button>
        </>
      }
    >
      <p>{confirm.message}</p>
    </Dialog>
  );
}
