import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, ApiError, Boat, Role } from "./api";
import { useAuth } from "./auth";
import { Calendar } from "./Calendar";
import { EditBoat } from "./EditBoat";
import { ShareDialog } from "./ShareDialog";
import { standing } from "./Landing";

const pct = (n: number) => `${Math.round(n * 1e6) / 1e6}%`;

function when(epochSeconds: number): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(epochSeconds * 1000));
}

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
          <input type="number" min={0.01} max={100} step="any" value={share} onChange={(e) => setShare(e.target.value)} required />
          <span className="hint">
            {boat.unallocated_percent > 0
              ? `${pct(boat.unallocated_percent)} of the boat is not held by any owner yet.`
              : "The owners hold all of the boat right now. You can be approved once an owner lowers their share or leaves."}
          </span>
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
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);

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
  const canEdit = boat.my_role === "owner";

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
        <div className="head-actions">
          {s && <span className={`badge ${s.tone}`}>{s.text}</span>}
          {canEdit && (
            <button type="button" className="button secondary" onClick={() => setEditing(true)}>
              Edit boat
            </button>
          )}
        </div>
      </section>
      {editing && (
        <EditBoat
          boat={boat}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            load();
          }}
        />
      )}

      {!approved && (
        <section className="card">
          <p>This boat is waiting for the administrator's approval. It will appear in the list, and people can ask to join, once it is approved.</p>
        </section>
      )}

      {sharing && boat.my_role === "owner" && (
        <ShareDialog
          boatId={boat.id}
          current={boat.members?.find((m) => m.user_id === me?.id)?.share_percent ?? 0}
          others={(boat.members ?? []).filter((m) => m.role === "owner" && m.user_id !== me?.id).reduce((t, m) => t + (m.share_percent ?? 0), 0)}
          unallocated={boat.unallocated_percent}
          onClose={() => setSharing(false)}
          onSaved={() => {
            setSharing(false);
            load();
          }}
        />
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
                      <span className="member-actions">
                        {m.role === "owner" && (
                          <button type="button" className="link-button" onClick={() => setSharing(true)}>
                            Change share
                          </button>
                        )}
                        <button type="button" className="link-button" onClick={() => remove(m.user_id, "Leave this boat? Your trips and sign-ons are removed.")}>
                          Leave
                        </button>
                      </span>
                    ) : (
                      boat.my_role === "owner" && m.role === "crew" && (
                        <button type="button" className="link-button" onClick={() => remove(m.user_id, `Remove ${m.name} from the boat? Their trips and sign-ons are removed.`)}>
                          Remove
                        </button>
                      )
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
            {boat.unallocated_percent > 0 && <p className="hint">{pct(boat.unallocated_percent)} of the boat is not held by any owner.</p>}
            {actionError && (
              <p className="error" role="alert">
                {actionError}
              </p>
            )}
            <p className="hint">Owners book the boat. Anyone aboard can sign on to a trip.</p>
            {boat.share_history && boat.share_history.length > 0 && (
              <details className="history">
                <summary>Share history</summary>
                <ul>
                  {boat.share_history.map((h, i) => (
                    <li key={i}>
                      <strong>{h.name}</strong>{" "}
                      {h.old_share === null ? `joined as an owner with ${pct(h.new_share ?? 0)}` : h.new_share === null ? `left, having held ${pct(h.old_share)}` : `${pct(h.old_share)} → ${pct(h.new_share)}`}
                      <span className="hint"> · {when(h.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
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
