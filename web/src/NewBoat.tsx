import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, ApiError } from "./api";
import { useAuth } from "./auth";
import { zones } from "./zones";

export function NewBoat() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [port, setPort] = useState("");
  const [description, setDescription] = useState("");
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [share, setShare] = useState("100");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (me === null) return <Navigate to="/login?next=/boats/new" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { id } = await api.addBoat({ name, home_port: port, description, timezone, share_percent: Number(share) });
      navigate(`/boats/${id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <section className="card narrow">
      <h1>Add a boat</h1>
      <p className="hint">The boat appears in the list once the administrator has approved it. You become its first owner.</p>
      <form onSubmit={submit} className="form">
        <label>
          Boat name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required autoFocus />
        </label>
        <label>
          Home port
          <input value={port} onChange={(e) => setPort(e.target.value)} maxLength={80} required placeholder="Marina del Rey, CA" />
        </label>
        <label>
          About the boat <span className="hint">(optional)</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} placeholder="J/35, 1985. Berth B-12." />
        </label>
        <label>
          Time zone <span className="hint">(the calendar shows the boat's own time)</span>
          <input list="zones" value={timezone} onChange={(e) => setTimezone(e.target.value)} required />
          <datalist id="zones">
            {zones().map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </label>
        <label>
          Your share of the boat, in percent
          <input type="number" min={1} max={100} step="any" value={share} onChange={(e) => setShare(e.target.value)} required />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <Link className="button secondary" to="/">
            Cancel
          </Link>
          <button className="button" disabled={busy}>
            Submit for approval
          </button>
        </div>
      </form>
    </section>
  );
}
