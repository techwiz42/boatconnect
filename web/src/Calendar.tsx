import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, Boat, Me, Trip } from "./api";
import { addMonths, dayOf, formatTime, formatWhen, gridRange, hiddenPerDay, layoutWeek, monthGrid, monthTitle, WEEKDAYS } from "./calendarMath";
import { TripDetail, TripForm } from "./TripDialogs";

const VISIBLE_LANES = 3;
const PALETTE = 8;

/** The same person always gets the same colour, so a glance at the month says who has the boat when. */
function hueOf(userId: string): number {
  let h = 0;
  for (const ch of userId) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % PALETTE) * 45 + 10;
}

export function Calendar({ boat, me }: { boat: Boat; me: Me }) {
  const timezone = boat.timezone;
  const today = dayOf(Date.now() / 1000, timezone);
  const [view, setView] = useState(() => ({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) }));
  const [trips, setTrips] = useState<Trip[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null); // the id of the trip being looked at
  const [form, setForm] = useState<{ trip?: Trip; day?: string } | null>(null);
  const isOwner = boat.my_role === "owner";

  const weeks = useMemo(() => monthGrid(view.year, view.month), [view]);

  const load = useCallback(async () => {
    const [from, to] = gridRange(weeks, timezone);
    try {
      setTrips(await api.trips(boat.id, from, to));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "could not load the calendar");
    }
  }, [boat.id, timezone, weeks]);

  useEffect(() => {
    void load();
  }, [load]);

  const step = (n: number) => setView((v) => addMonths(v.year, v.month, n));
  const current = trips.find((t) => t.id === open) ?? null;
  const thisMonth = trips.filter((t) => {
    const first = dayOf(t.start, timezone).slice(0, 7);
    const last = dayOf(t.end - 1, timezone).slice(0, 7);
    const key = `${view.year}-${String(view.month).padStart(2, "0")}`;
    return first <= key && last >= key;
  });

  return (
    <section className="calendar" aria-label="Boat calendar">
      <div className="calendar-head">
        <h2>{monthTitle(view.year, view.month)}</h2>
        <div className="calendar-nav">
          <button type="button" className="button secondary" onClick={() => step(-1)} aria-label="Previous month">
            ‹
          </button>
          <button type="button" className="button secondary" onClick={() => setView({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) })}>
            Today
          </button>
          <button type="button" className="button secondary" onClick={() => step(1)} aria-label="Next month">
            ›
          </button>
          {isOwner && (
            <button type="button" className="button" onClick={() => setForm({ day: today })}>
              New trip
            </button>
          )}
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="month" role="grid">
        <div className="weekdays" role="row">
          {WEEKDAYS.map((d) => (
            <div key={d} role="columnheader">
              {d}
            </div>
          ))}
        </div>
        {weeks.map((week) => {
          const segments = layoutWeek(week, trips, timezone);
          const lanes = segments.reduce((m, s) => Math.max(m, s.lane + 1), 0);
          const shown = Math.min(lanes, VISIBLE_LANES);
          const hidden = hiddenPerDay(segments, VISIBLE_LANES);
          const rows = shown + (hidden.some((n) => n > 0) ? 1 : 0);
          return (
            <div className="week" key={week[0]!.key} role="row" style={{ gridTemplateRows: `1.8rem repeat(${rows}, 1.5rem) minmax(0.3rem, 1fr)` }}>
              {week.map((d, c) => (
                <button
                  type="button"
                  key={d.key}
                  role="gridcell"
                  className={`day${d.inMonth ? "" : " outside"}${d.key === today ? " today" : ""}`}
                  style={{ gridColumn: c + 1, gridRow: `1 / span ${rows + 2}` }}
                  disabled={!isOwner}
                  onClick={() => setForm({ day: d.key })}
                  aria-label={`${d.key}${isOwner ? ", add a trip" : ""}`}
                  title={isOwner ? "Add a trip on this day" : undefined}
                >
                  <span className="num">{d.day === 1 ? `${new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(d.year, d.month - 1, 1)))} 1` : d.day}</span>
                </button>
              ))}
              {segments
                .filter((s) => s.lane < VISIBLE_LANES)
                .map((s) => {
                  const startsHere = !s.continuesBefore;
                  return (
                    <button
                      type="button"
                      key={`${s.trip.id}-${week[0]!.key}`}
                      className={`bar${s.continuesBefore ? " from-before" : ""}${s.continuesAfter ? " to-after" : ""}${s.trip.i_am_aboard ? " mine" : ""}`}
                      style={{ gridColumn: `${s.startCol + 1} / ${s.endCol + 2}`, gridRow: s.lane + 2, ["--hue" as string]: hueOf(s.trip.created_by) }}
                      onClick={() => setOpen(s.trip.id)}
                      title={`${s.trip.title}: ${formatWhen(s.trip.start, s.trip.end, timezone)}`}
                    >
                      {s.trip.i_am_aboard && <span aria-label="you are aboard">✓ </span>}
                      {startsHere && s.startCol === s.endCol && <span className="time">{formatTime(s.trip.start, timezone)} </span>}
                      {s.trip.title}
                    </button>
                  );
                })}
              {hidden.map((n, c) =>
                n > 0 ? (
                  <button type="button" key={`more-${c}`} className="more" style={{ gridColumn: c + 1, gridRow: shown + 2 }} onClick={() => setOpen(segments.find((s) => s.lane >= VISIBLE_LANES && s.startCol <= c && s.endCol >= c)?.trip.id ?? null)}>
                    +{n}
                    <span className="word"> more</span>
                  </button>
                ) : null,
              )}
            </div>
          );
        })}
      </div>

      <h3 className="agenda-title">Trips in {monthTitle(view.year, view.month)}</h3>
      {thisMonth.length === 0 ? (
        <p className="hint">No trips this month{isOwner ? ". Click a day to book the boat." : "."}</p>
      ) : (
        <ul className="agenda">
          {thisMonth.map((t) => (
            <li key={t.id}>
              <button type="button" className="agenda-item" style={{ ["--hue" as string]: hueOf(t.created_by) }} onClick={() => setOpen(t.id)}>
                <span className="agenda-when">{formatWhen(t.start, t.end, timezone)}</span>
                <strong>{t.title}</strong>
                <span className="hint">
                  {t.created_by_name} · {t.aboard.length}
                  {t.capacity !== null ? `/${t.capacity}` : ""} aboard{t.i_am_aboard ? " · you are aboard" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {current && !form && (
        <TripDetail
          trip={current}
          timezone={timezone}
          me={me}
          onClose={() => setOpen(null)}
          onChanged={() => void load()}
          onEdit={() => setForm({ trip: current })}
        />
      )}
      {form && (
        <TripForm
          boatId={boat.id}
          timezone={timezone}
          trip={form.trip}
          day={form.day}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null);
            setOpen(null);
            void load();
          }}
        />
      )}
    </section>
  );
}
