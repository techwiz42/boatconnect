import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "./api";
import { useAuth } from "./auth";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { setMe } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const registering = mode === "register";
  const next = params.get("next");
  const after = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setMe(registering ? await api.register(email, name, password) : await api.login(email, password));
      navigate(after, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <section className="card narrow">
      <h1>{registering ? "Create an account" : "Log in"}</h1>
      <form onSubmit={submit} className="form">
        {registering && (
          <label>
            Your name <span className="hint">(shown to the people on your boats)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required autoComplete="name" />
          </label>
        )}
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" autoFocus />
        </label>
        <label>
          Password {registering && <span className="hint">(at least 10 characters)</span>}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={registering ? 10 : undefined} autoComplete={registering ? "new-password" : "current-password"} />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="button" disabled={busy}>
          {registering ? "Create account" : "Log in"}
        </button>
      </form>
      {!registering && (
        <p className="hint">
          <Link to="/forgot">Forgot your password?</Link>
        </p>
      )}
      <p className="hint">
        {registering ? (
          <>
            Already have an account? <Link to={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Log in</Link>
          </>
        ) : (
          <>
            New here? <Link to={`/register${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Create an account</Link>
          </>
        )}
      </p>
    </section>
  );
}
