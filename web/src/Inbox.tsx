import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, ApiError, Inbox as InboxData } from "./api";
import { useAuth } from "./auth";

export function Inbox() {
  const { me, refreshInbox } = useAuth();
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.inbox().then(setInbox, () => setError("could not load your requests"));
  }, []);

  useEffect(() => {
    if (me) load();
  }, [me, load]);

  async function decide(job: () => Promise<unknown>) {
    setError("");
    try {
      await job();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
    }
    load();
    refreshInbox();
  }

  if (me === null) return <Navigate to="/login?next=/inbox" replace />;
  const empty = inbox && inbox.boats.length === 0 && inbox.requests.length === 0;

  return (
    <section className="card">
      <h1>Waiting for you</h1>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {inbox === null && !error && <p className="hint">Loading…</p>}
      {empty && <p className="hint">Nothing is waiting for your decision.</p>}

      {inbox && inbox.boats.length > 0 && (
        <>
          <h2>New boats</h2>
          <ul className="queue">
            {inbox.boats.map((b) => (
              <li key={b.id}>
                <div>
                  <Link to={`/boats/${b.id}`}>
                    <strong>{b.name}</strong>
                  </Link>{" "}
                  <span className="hint">{b.home_port}</span>
                  {b.description && <p>{b.description}</p>}
                </div>
                <div className="actions">
                  <button className="button" onClick={() => decide(() => api.decideBoat(b.id, true))}>
                    Approve
                  </button>
                  <button className="button secondary" onClick={() => decide(() => api.decideBoat(b.id, false))}>
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {inbox && inbox.requests.length > 0 && (
        <>
          <h2>Requests to join</h2>
          <ul className="queue">
            {inbox.requests.map((r) => (
              <li key={r.id}>
                <div>
                  <strong>{r.user_name}</strong> asks to join{" "}
                  <Link to={`/boats/${r.boat_id}`}>
                    <strong>{r.boat_name}</strong>
                  </Link>{" "}
                  as {r.role}
                  {r.role === "owner" ? ` with a ${r.share_percent}% share` : ""}
                  {r.message && <p className="notes">“{r.message}”</p>}
                </div>
                <div className="actions">
                  <button className="button" onClick={() => decide(() => api.decideRequest(r.id, true))}>
                    Approve
                  </button>
                  <button className="button secondary" onClick={() => decide(() => api.decideRequest(r.id, false))}>
                    Decline
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
