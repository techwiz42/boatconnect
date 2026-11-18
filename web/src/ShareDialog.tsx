import { FormEvent, useState } from "react";
import { api, ApiError } from "./api";
import { Modal } from "./Modal";

const pct = (n: number) => `${Math.round(n * 1e6) / 1e6}%`;

/** An owner changes their own share. Lowering it makes room for another owner; raising it only takes room nobody holds. */
export function ShareDialog({ boatId, current, others, unallocated, onClose, onSaved }: { boatId: string; current: number; others: number; unallocated: number; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState(String(current));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const most = Math.round((current + unallocated) * 1e6) / 1e6;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.setShare(boatId, Number(value));
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <Modal title="Your share of the boat" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <p>
          You hold <strong>{pct(current)}</strong>
          {others > 0 ? `; the other owners hold ${pct(others)}` : ""}
          {unallocated > 0 ? `; ${pct(unallocated)} is held by no one` : ""}. Owners' shares together can be at most 100%, so you can set yours anywhere from 0.01% up to <strong>{pct(most)}</strong> right now.
        </p>
        <p className="hint">
          {unallocated > 0
            ? "The room that is free is yours to take, or to leave for a new owner."
            : "Your share can grow as soon as another owner lowers theirs, sells to you or leaves the boat."}
        </p>
        <label>
          Your share, in percent
          <input type="number" min={0.01} max={most} step="any" value={value} onChange={(e) => setValue(e.target.value)} required autoFocus />
        </label>
        <p className="hint">
          To add a new owner, lower your share to make room; they ask to join as an owner and the administrator approves. If you sell to an owner already here, lower yours and
          they raise theirs. Every change is kept in the boat's share history.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="button" disabled={busy}>
            Save my share
          </button>
        </div>
      </form>
    </Modal>
  );
}
