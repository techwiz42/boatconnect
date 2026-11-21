import { FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, ApiError, Person } from "./api";
import { useAuth } from "./auth";
import { Confirm } from "./Confirm";
import { Modal } from "./Modal";

const sayError = (err: unknown) => (err instanceof ApiError ? err.message : "something went wrong");
const day = (t: number | null) => (t ? new Date(t * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "never");

/** The administrator's list of everyone registered: change someone's name, email or telephone, or delete them. */
export function People() {
  const { me } = useAuth();
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Person | null>(null);
  const [deleting, setDeleting] = useState<Person | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.people().then(setPeople, (err: unknown) => setError(sayError(err)));
  }, []);

  useEffect(() => {
    if (me?.is_admin) load();
  }, [me, load]);

  async function remove(p: Person) {
    setBusy(true);
    setError("");
    try {
      await api.deletePerson(p.id);
      setDeleting(null);
      load();
    } catch (err) {
      setError(sayError(err));
      setDeleting(null);
    }
    setBusy(false);
  }

  if (me === null) return <Navigate to="/login?next=/people" replace />;
  if (me && !me.is_admin) return <Navigate to="/" replace />;

  return (
    <section className="card">
      <h1>People</h1>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {deleting && (
        <Confirm
          text={`Delete ${deleting.name} (${deleting.email})? They are removed from their boats, with the trips they booked and their sign-ons. This cannot be undone.`}
          yes={`Delete ${deleting.name}`}
          onYes={() => void remove(deleting)}
          onNo={() => setDeleting(null)}
          busy={busy}
        />
      )}
      {!people ? (
        <p className="hint">Loading…</p>
      ) : (
        <ul className="people">
          {people.map((p) => (
            <li key={p.id}>
              <span>
                <strong>{p.name}</strong>
                <br />
                <span className="hint">
                  {p.email} · {p.phone || "no telephone yet"} · {p.boats} boat{p.boats === 1 ? "" : "s"} · last here {day(p.last_login_at)}
                </span>
              </span>
              <span className="member-actions">
                <button type="button" className="link-button" onClick={() => setEditing(p)}>
                  Edit
                </button>
                {p.id !== me?.id && (
                  <button type="button" className="link-button" onClick={() => setDeleting(p)}>
                    Delete
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <EditPerson
          person={editing}
          mine={editing.id === me?.id}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </section>
  );
}

function EditPerson({ person, mine, onClose, onSaved }: { person: Person; mine: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(person.name);
  const [email, setEmail] = useState(person.email);
  const [phone, setPhone] = useState(person.phone);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.editPerson(person.id, { name, email, phone });
      onSaved();
    } catch (err) {
      setError(sayError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title="Edit person" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required />
        </label>
        <label>
          Email {mine ? <span className="hint">(yours: change it in Your account)</span> : <span className="hint">(changing it signs them out)</span>}
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={mine} />
        </label>
        <label>
          Telephone
          <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={40} required placeholder="+1 310 555 0123" />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="button" disabled={busy}>
            Save
          </button>
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
