import { Trip } from "./api";
import { formatTime } from "./calendarMath";
import { Modal } from "./Modal";

/** Who is on the boat on one calendar day: every trip touching it, with the skipper and the crew signed on. */
export function DayDialog({
  day,
  trips,
  timezone,
  canAdd,
  onOpenTrip,
  onAdd,
  onClose,
}: {
  day: string;
  trips: Trip[];
  timezone: string;
  canAdd: boolean;
  onOpenTrip: (id: string) => void;
  onAdd: () => void;
  onClose: () => void;
}) {
  const [y, m, d] = day.split("-").map(Number);
  const heading = new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date(Date.UTC(y!, m! - 1, d!)));
  return (
    <Modal title={heading} onClose={onClose}>
      {trips.length === 0 && <p className="hint">No trips this day.</p>}
      <ul className="day-trips">
        {trips.map((t) => {
          const crew = t.aboard.filter((a) => a.user_id !== t.created_by);
          return (
            <li key={t.id}>
              <button
                type="button"
                className="link-button"
                onClick={() => onOpenTrip(t.id)}
              >
                <strong>{t.title}</strong>
              </button>
              <span className="hint">
                {" "}
                {formatTime(t.start, timezone)} to {formatTime(t.end, timezone)}{" "}
                · skipper {t.created_by_name}
              </span>
              <p className="crew-line">
                {crew.length === 0
                  ? "No crew signed on yet"
                  : `Crew (${crew.length}${t.capacity !== null ? `, ${t.aboard.length} of ${t.capacity} aboard` : ""}): ${crew.map((a) => a.name).join(", ")}`}
              </p>
            </li>
          );
        })}
      </ul>
      {canAdd && (
        <div className="actions">
          <button type="button" className="button" onClick={onAdd}>
            {trips.length === 0
              ? "Book the boat this day"
              : "Add another trip this day"}
          </button>
        </div>
      )}
    </Modal>
  );
}
