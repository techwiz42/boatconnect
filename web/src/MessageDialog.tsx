import { FormEvent, useState } from "react";
import { api, ApiError } from "./api";
import { Modal } from "./Modal";

/** A member writes to everyone else on the boat. It goes by email from boatconnect; replies come to the sender's own address. */
export function MessageDialog({ boatId, boatName, others, myEmail, onClose }: { boatId: string; boatName: string; others: number; myEmail: string; onClose: () => void }) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setSent((await api.messageCrew(boatId, subject, body)).sent);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
    }
    setBusy(false);
  }

  return (
    <Modal title={`Message the crew of ${boatName}`} onClose={onClose}>
      {sent !== null ? (
        <>
          <p role="status">
            Sent to {sent} {sent === 1 ? "person" : "people"}. Their replies come to {myEmail}.
          </p>
          <div className="actions">
            <button type="button" className="button" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      ) : (
        <form onSubmit={submit} className="form">
          <p className="hint">
            Emailed to the {others} other {others === 1 ? "member" : "members"} of this boat. When they reply, the answer comes to you at {myEmail}, which they will then see.
          </p>
          <label>
            Subject <span className="hint">(optional)</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={100} autoFocus />
          </label>
          <label>
            Message
            <textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} rows={6} required />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <button className="button" disabled={busy || !body.trim()}>
              Send
            </button>
            <button type="button" className="button secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
