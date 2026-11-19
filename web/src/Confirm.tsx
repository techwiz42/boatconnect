/** An "are you sure" built into the page. (The browser's own confirm box can be dismissed or silenced by the browser without a trace, and then nothing happens.) */
export function Confirm({ text, yes, onYes, onNo, busy = false }: { text: string; yes: string; onYes: () => void; onNo: () => void; busy?: boolean }) {
  return (
    <div className="confirm" role="alertdialog" aria-label={text}>
      <p>{text}</p>
      <div className="actions">
        <button type="button" className="button danger" disabled={busy} onClick={onYes}>
          {yes}
        </button>
        <button type="button" className="button secondary" disabled={busy} onClick={onNo}>
          Keep it
        </button>
      </div>
    </div>
  );
}
