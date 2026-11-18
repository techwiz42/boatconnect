import { FormEvent, useState } from "react";
import { api, ApiError, Me, Trip } from "./api";
import { formatWhen, fromLocalInput, toLocalInput } from "./calendarMath";
import { Modal } from "./Modal";

const hhmm = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** Making a trip, or changing one. A new trip from a clicked day starts at 9:00 and ends at 17:00 that day. */
export function TripForm({ boatId, timezone, trip, day, onClose, onSaved }: { boatId: string; timezone: string; trip?: Trip; day?: string; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(trip?.title ?? "");
  const [start, setStart] = useState(trip ? toLocalInput(trip.start, timezone) : `${day ?? ""}T${hhmm(9)}`);
  const [end, setEnd] = useState(trip ? toLocalInput(trip.end, timezone) : `${day ?? ""}T${hhmm(17)}`);
  const [capacity, setCapacity] = useState(trip?.capacity == null ? "" : String(trip.capacity));
  const [notes, setNotes] = useState(trip?.notes ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const from = fromLocalInput(start, timezone);
    const to = fromLocalInput(end, timezone);
    if (from === null || to === null) return setError("choose a start and an end, each with a date and a time");
    if (to <= from) return setError("the trip must end after it starts");
    setBusy(true);
    setError("");
    const input = { title, start: from, end: to, capacity: capacity.trim() === "" ? null : Number(capacity), notes };
    try {
      if (trip) await api.changeTrip(trip.id, input);
      else await api.addTrip(boatId, input);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <Modal title={trip ? "Change the trip" : "New trip"} onClose={onClose}>
      <form onSubmit={submit} className="form">
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} required autoFocus placeholder="Catalina weekend" />
        </label>
        <div className="row">
          <label>
            Starts
            <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required />
          </label>
          <label>
            Ends
            <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </label>
        </div>
        <p className="hint">Times are the boat's own ({timezone.replace(/_/g, " ")}).</p>
        <label>
          Most people aboard <span className="hint">(optional)</span>
          <input type="number" min={1} max={100} value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="no limit" />
        </label>
        <label>
          Notes <span className="hint">(optional)</span>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} rows={3} />
        </label>
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
            {trip ? "Save" : "Book the boat"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** One trip: when, who is aboard, and what the viewer may do about it. */
export function TripDetail({ trip, timezone, me, onClose, onChanged, onEdit }: { trip: Trip; timezone: string; me: Me; onClose: () => void; onChanged: () => void; onEdit: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const full = trip.capacity !== null && trip.aboard.length >= trip.capacity;

  async function act(job: () => Promise<unknown>, closeAfter = false) {
    setBusy(true);
    setError("");
    try {
      await job();
      onChanged();
      if (closeAfter) onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
    }
    setBusy(false);
  }

  return (
    <Modal title={trip.title} onClose={onClose}>
      <p className="when">{formatWhen(trip.start, trip.end, timezone)}</p>
      <p className="hint">Booked by {trip.created_by_name}</p>
      {trip.notes && <p className="notes">{trip.notes}</p>}
      <h3>
        Aboard ({trip.aboard.length}
        {trip.capacity !== null ? ` of ${trip.capacity}` : ""})
      </h3>
      <ul className="aboard">
        {trip.aboard.map((a) => (
          <li key={a.user_id}>
            <span>
              {a.name}
              {a.user_id === trip.created_by ? " (skipper)" : ""}
            </span>
            {a.user_id !== trip.created_by && (a.user_id === me.id || trip.can_edit) && (
              <button type="button" className="link-button" disabled={busy} onClick={() => act(() => api.signOff(trip.id, a.user_id))}>
                {a.user_id === me.id ? "Sign off" : "Remove"}
              </button>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        {!trip.i_am_aboard && (
          <button type="button" className="button" disabled={busy || full} onClick={() => act(() => api.signOn(trip.id))}>
            {full ? "Trip is full" : "Sign on as crew"}
          </button>
        )}
        {trip.can_edit && (
          <>
            <button type="button" className="button secondary" onClick={onEdit}>
              Change
            </button>
            <button
              type="button"
              className="button danger"
              disabled={busy}
              onClick={() => window.confirm("Cancel this trip? Everyone signed on loses it.") && act(() => api.cancelTrip(trip.id), true)}
            >
              Cancel trip
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}
