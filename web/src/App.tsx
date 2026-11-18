import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { AuthPage } from "./AuthPage";
import { AuthProvider, useAuth } from "./auth";
import { BoatPage } from "./BoatPage";
import { Inbox } from "./Inbox";
import { Landing } from "./Landing";
import { NewBoat } from "./NewBoat";

function Header() {
  const { me, setMe, inboxCount } = useAuth();

  async function logout() {
    await api.logout().catch(() => undefined);
    setMe(null);
    window.location.assign("/");
  }

  return (
    <header className="site-header">
      <Link to="/" className="brand">
        <img src="/favicon.svg" alt="" width={28} height={28} />
        boatconnect
      </Link>
      <nav aria-label="Main">
        <NavLink to="/" end>
          Boats
        </NavLink>
        {me && <NavLink to="/boats/new">Add a boat</NavLink>}
        {me && (
          <NavLink to="/inbox">
            Waiting for you{inboxCount > 0 && <span className="count">{inboxCount}</span>}
          </NavLink>
        )}
        {me === null && <NavLink to="/login">Log in</NavLink>}
        {me === null && <NavLink to="/register">Register</NavLink>}
        {me && (
          <span className="who">
            {me.name}
            <button type="button" className="link-button" onClick={logout}>
              Log out
            </button>
          </span>
        )}
      </nav>
    </header>
  );
}

function NotFound() {
  return (
    <section className="card">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the boats</Link>
      </p>
    </section>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Header />
        <main className="page">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/boats/new" element={<NewBoat />} />
            <Route path="/boats/:id" element={<BoatPage />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
        <footer className="site-footer">
          © 2026 Peter Sisk · <a href="mailto:j35.scooter@gmail.com">j35.scooter@gmail.com</a> ·{" "}
          <a href="https://github.com/techwiz42/boatconnect" target="_blank" rel="noopener noreferrer">
            GitHub
          </a>
        </footer>
      </AuthProvider>
    </BrowserRouter>
  );
}
