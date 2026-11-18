import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Boat } from "./api";
import { useAuth } from "./auth";

export function standing(b: Boat): { text: string; tone: string } | null {
  if (b.status === "pending") return { text: "Waiting for approval", tone: "wait" };
  if (b.status === "rejected") return { text: "Not approved", tone: "bad" };
  if (b.my_role === "owner") return { text: "You are an owner", tone: "good" };
  if (b.my_role === "crew") return { text: "You are crew", tone: "good" };
  if (b.my_request) return { text: `Your ${b.my_request.role} request is waiting`, tone: "wait" };
  return null;
}

export function Landing() {
  const { me } = useAuth();
  const [boats, setBoats] = useState<Boat[] | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.boats().then(setBoats, () => setError("could not load the boats"));
  }, [me?.id]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (boats ?? []).filter((b) => !q || `${b.name} ${b.home_port} ${b.description}`.toLowerCase().includes(q));
  }, [boats, search]);

  return (
    <>
      <section className="hero card">
        <h1>Share a boat. Share the calendar.</h1>
        <p>
          boatconnect is where the people who use a boat keep track of who has it when. Find a boat, ask to join as an owner or as crew, and see every trip on a month calendar.
          Owners book the boat; crew sign on to a trip.
        </p>
        <div className="actions">
          {me ? (
            <Link className="button" to="/boats/new">
              Add a boat
            </Link>
          ) : (
            <>
              <Link className="button" to="/register">
                Create an account
              </Link>
              <Link className="button secondary" to="/login">
                Log in
              </Link>
            </>
          )}
        </div>
      </section>

      <section className="card">
        <div className="list-head">
          <h2>Boats</h2>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name or port" aria-label="Search boats" />
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {boats === null && !error && <p className="hint">Loading…</p>}
        {boats !== null && shown.length === 0 && (
          <p className="hint">{boats.length === 0 ? "No boats yet. Be the first to add one." : "No boat matches that search."}</p>
        )}
        <ul className="boats">
          {shown.map((b) => {
            const s = standing(b);
            return (
              <li key={b.id}>
                <Link to={`/boats/${b.id}`} className="boat-card">
                  <span className="boat-name">{b.name}</span>
                  <span className="hint">
                    {b.home_port} · {b.owner_count} owner{b.owner_count === 1 ? "" : "s"}, {b.crew_count} crew
                  </span>
                  {b.description && <span className="boat-desc">{b.description}</span>}
                  {s && <span className={`badge ${s.tone}`}>{s.text}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}
