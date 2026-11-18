import { FormEvent, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "./api";
import { useAuth } from "./auth";

const sayError = (err: unknown) => (err instanceof ApiError ? err.message : "something went wrong");

/** Who you are, and whether boatconnect emails you about trips. */
export function Account() {
  const { me, setMe } = useAuth();
  const [error, setError] = useState("");
  const [on, setOn] = useState<boolean | null>(null); // what the switch shows while a change is being saved; null: what the server last said
  if (me === null) return <Navigate to="/login?next=/account" replace />;
  if (!me) return <p className="hint">Loading…</p>;
  const checked = on ?? me.email_trips;

  async function toggle(wanted: boolean) {
    setOn(wanted); // the switch moves at once; it goes back only if saving fails
    setError("");
    try {
      setMe(await api.setPreferences(wanted));
    } catch (err) {
      setError(sayError(err));
    }
    setOn(null);
  }

  return (
    <section className="card narrow">
      <h1>Your account</h1>
      <p>
        <strong>{me.name}</strong>
        <br />
        <span className="hint">{me.email}</span>
      </p>
      <h2>Email</h2>
      <label className="setting">
        <input type="checkbox" checked={checked} onChange={(e) => toggle(e.target.checked)} />
        <span>
          Email me when a trip on one of my boats is booked, changed or cancelled
          <br />
          <span className="hint">Notices about requests to join your boats, and decisions on your own requests, are always sent.</span>
        </span>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** "Forgot your password?": ask for a link by email. The answer is the same whether or not the address has an account. */
export function Forgot() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.forgot(email);
      setSent(true);
    } catch (err) {
      setError(sayError(err));
    }
    setBusy(false);
  }

  return (
    <section className="card narrow">
      <h1>Forgot your password?</h1>
      {sent ? (
        <>
          <p className="good-note" role="status">
            If that address has a boatconnect account, we have emailed it a link to choose a new password. The link works once and expires in an hour.
          </p>
          <p className="hint">Nothing arrived? Check your spam folder, or try again in a few minutes.</p>
          <p>
            <Link to="/login">Back to log in</Link>
          </p>
        </>
      ) : (
        <form onSubmit={submit} className="form">
          <p className="hint">Enter the email address of your account and we will send you a link to choose a new password.</p>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" autoFocus />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button" disabled={busy}>
            Send me a link
          </button>
          <p className="hint">
            <Link to="/login">Back to log in</Link>
          </p>
        </form>
      )}
    </section>
  );
}

/** The page the emailed link opens: choose a new password. */
export function Reset() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== again) return setError("the two passwords are not the same");
    setBusy(true);
    setError("");
    try {
      await api.reset(token, password);
      setDone(true);
    } catch (err) {
      setError(sayError(err));
      setBusy(false);
    }
  }

  if (!token)
    return (
      <section className="card narrow">
        <h1>Choose a new password</h1>
        <p className="error">This link is incomplete. Open the link from the email again, or ask for a new one.</p>
        <p>
          <Link to="/forgot">Ask for a new link</Link>
        </p>
      </section>
    );

  return (
    <section className="card narrow">
      <h1>Choose a new password</h1>
      {done ? (
        <>
          <p className="good-note" role="status">
            Your password was changed. Anywhere you were logged in has been logged out.
          </p>
          <Link className="button" to="/login">
            Log in
          </Link>
        </>
      ) : (
        <form onSubmit={submit} className="form">
          <label>
            New password <span className="hint">(at least 10 characters)</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} autoComplete="new-password" autoFocus />
          </label>
          <label>
            The same again
            <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} required minLength={10} autoComplete="new-password" />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button" disabled={busy}>
            Change my password
          </button>
          <p className="hint">
            Expired or used link? <Link to="/forgot">Ask for a new one</Link>.
          </p>
        </form>
      )}
    </section>
  );
}

/** The link at the foot of a trip email. Opening it asks first, because mail programs sometimes open links on their own. */
export function Unsubscribe() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { me } = useAuth();
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function stop() {
    setBusy(true);
    setError("");
    try {
      await api.unsubscribe(token);
      setDone(true);
    } catch (err) {
      setError(sayError(err));
    }
    setBusy(false);
  }

  return (
    <section className="card narrow">
      <h1>Emails about trips</h1>
      {!token ? (
        <p className="error">This link is incomplete. Use the link at the bottom of one of the emails.</p>
      ) : done ? (
        <>
          <p className="good-note" role="status">
            Done. You will not get emails about trips any more.
          </p>
          <p className="hint">
            You can turn them back on any time in <Link to={me ? "/account" : "/login?next=/account"}>your account</Link>.
          </p>
        </>
      ) : (
        <>
          <p>Stop the emails that tell you when a trip on one of your boats is booked, changed or cancelled?</p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="button" onClick={stop} disabled={busy}>
            Stop emails about trips
          </button>
        </>
      )}
    </section>
  );
}
