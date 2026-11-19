import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { Confirm } from "./Confirm";
import { Modal } from "./Modal";

/** The person's private calendar address: add it to Google, Apple or Outlook calendar once, and every trip of every boat they belong to shows there and stays current. */
export function FeedDialog({ onClose }: { onClose: () => void }) {
  const [path, setPath] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [asking, setAsking] = useState(false); // making a new link waits for a yes
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.calendarFeed().then((r) => setPath(r.path), (err: unknown) => setError(err instanceof ApiError ? err.message : "could not get your link"));
  }, []);

  const url = path ? `${window.location.origin}${path}` : "";
  const webcal = url.replace(/^https?:/, "webcal:");

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      document.querySelector<HTMLInputElement>("#feed-url")?.select();
      setError("Your browser would not copy it; the link is selected, so press Ctrl+C (or Cmd+C).");
    }
  }

  async function reset() {
    setAsking(false);
    setBusy(true);
    setError("");
    try {
      setPath((await api.resetCalendarFeed()).path);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
    }
    setBusy(false);
  }

  return (
    <Modal title="Add the boat calendar to your calendar" onClose={onClose}>
      <p>
        This is your own link. Add it once to Google, Apple or Outlook Calendar and the trips of <strong>every boat you belong to</strong> appear there, each marked with the boat's
        name, and stay up to date.
      </p>
      <div className="copy-row">
        <input id="feed-url" readOnly value={url || "…"} onFocus={(e) => e.currentTarget.select()} aria-label="Your private calendar link" />
        <button type="button" className="button" onClick={copy} disabled={!url}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <ol className="steps">
        <li>
          <strong>Apple Calendar:</strong> <a href={webcal}>click here to subscribe</a>, or use File → New Calendar Subscription and paste the link.
        </li>
        <li>
          <strong>Google Calendar:</strong> on a computer, click + next to "Other calendars", choose "From URL", paste the link, and add it.
        </li>
        <li>
          <strong>Outlook:</strong> Add calendar → Subscribe from web, then paste the link.
        </li>
      </ol>
      <p className="hint">
        Calendars refresh a subscribed link on their own schedule: Apple within about an hour, Google within about a day. Keep the link private: anyone who has it can read your boats'
        trips and who is aboard.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {asking && <Confirm text="Make a new link? The old one stops working, so any calendar that uses it must be given the new one." yes="Make a new link" busy={busy} onYes={() => void reset()} onNo={() => setAsking(false)} />}
      <div className="actions">
        <button type="button" className="button secondary" onClick={() => setAsking(true)} disabled={busy || !path}>
          Make a new link
        </button>
        <button type="button" className="button secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}
