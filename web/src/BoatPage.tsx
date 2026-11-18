import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, ApiError, Boat, Role } from "./api";
import { useAuth } from "./auth";
import { Calendar } from "./Calendar";
import { standing } from "./Landing";

function JoinForm({ boat, onSent }: { boat: Boat; onSent: () => void }) {
  const [role, setRole] = useState<Role>("crew");
  const [share, setShare] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.join(boat.id, role, role === "owner" ? Number(share) : null, message);
      onSent();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="form">
      <h2>Ask to join</h2>
      <fieldset className="choice">
        <label>
          <input type="radio" name="role" checked={role === "crew"} onChange={() => setRole("crew")} /> Crew <span className="hint">(an owner approves you; you sign on to their trips)</span>
        </label>
        <label>
          <input type="radio" name="role" checked={role === "owner"} onChange={() => setRole("owner")} /> Owner <span className="hint">(the administrator approves you; you can book the boat)</span>
        </label>
      </fieldset>
      {role === "owner" && (
        <label>
          Your share of the boat, in percent
          <input type="number" min={1} max={100} step="any" value={share} onChange={(e) => setShare(e.target.value)} required />
        </label>
      )}
      <label>
        A note for whoever decides <span className="hint">(optional)</span>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} rows={3} />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="button" disabled={busy}>
        Send request
      </button>
    </form>
  );
}

export function BoatPage() {
  const { id = "" } = useParams();
  const location = useLocation();
  const { me } = useAuth();
  const [boat, setBoat] = useState<Boat | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  const load = useCallback(() => {
    api.boat(id).then(
      (b) => {
        setBoat(b);
        setError("");
      },
      (err: unknown) => setError(err instanceof ApiError && err.status === 404 ? "There is no such boat." : "Could not load the boat."),
    );
  }, [id]);

  useEffect(load, [load, me?.id]);

  async function remove(userId: string, text: string) {
    if (!boat || !window.confirm(text)) return;
    setActionError("");
    try {
      await api.removeMember(boat.id, userId);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "something went wrong");
    }
  }

  if (error) return <section className="card"><p className="error">{error}</p><Link to="/">Back to the boats</Link></section>;
  if (!boat) return <p className="hint">Loading…</p>;

  const s = standing(boat);
  const member = boat.my_role !== null;
  const approved = boat.status === "approved";

  return (
    <>
      <section className="card boat-head">
        <div>
          <h1>{boat.name}</h1>
          <p className="hint">
            {boat.home_port} · {boat.timezone.replace(/_/g, " ")} · {boat.owner_count} owner{boat.owner_count === 1 ? "" : "s"}, {boat.crew_count} crew
          </p>
          {boat.description && <p>{boat.description}</p>}
        </div>
        {s && <span className={`badge ${s.tone}`}>{s.text}</span>}
      </section>

      {!approved && (
        <section className="card">
          <p>This boat is waiting for the administrator's approval. It will appear in the list, and people can ask to join, once it is approved.</p>
        </section>
      )}

      {approved && member && me && (
        <div className="boat-layout">
          <Calendar boat={boat} me={me} />
          <aside className="card members">
            <h2>Members</h2>
            {boat.members?.length ? (
              <ul className="member-list">
                {boat.members.map((m) => (
                  <li key={m.user_id}>
                    <span>
                      {m.name}
                      <span className="hint">
                        {" "}
                        · {m.role === "owner" ? `owner, ${m.share_percent}%` : "crew"}
                      </span>
                    </span>
                    {m.user_id === me.id ? (
                      <button type="button" className="link-button" onClick={() => remove(m.user_id, "Leave this boat? Your trips and sign-ons are removed.")}>
                        Leave
                      </button>
                    ) : (
                      boat.my_role === "owner" && (
                        <button type="button" className="link-button" onClick={() => remove(m.user_id, `Remove ${m.name} from the boat? Their trips and sign-ons are removed.`)}>
                          Remove
                        </button>
                      )
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
            {actionError && (
              <p className="error" role="alert">
                {actionError}
              </p>
            )}
            <p className="hint">Owners book the boat. Anyone aboard can sign on to a trip.</p>
          </aside>
        </div>
      )}

      {approved && !member && (
        <section className="card narrow">
          {!me ? (
            <>
              <h2>Ask to join</h2>
              <p>
                <Link to={`/login?next=${encodeURIComponent(location.pathname)}`}>Log in</Link> or <Link to={`/register?next=${encodeURIComponent(location.pathname)}`}>create an account</Link> to ask to join {boat.name}.
              </p>
            </>
          ) : boat.my_request ? (
            <p>
              Your request to join as {boat.my_request.role}
              {boat.my_request.role === "owner" ? ` (${boat.my_request.share_percent}%)` : ""} is waiting for {boat.my_request.role === "owner" ? "the administrator" : "an owner"} to decide.
            </p>
          ) : (
            <JoinForm boat={boat} onSent={load} />
          )}
        </section>
      )}
    </>
  );
}
