// Month-calendar arithmetic. Everything about a boat's calendar is in the boat's own time zone ("a trip on Saturday" means Saturday where the boat is), while the server
// stores and sends plain UTC seconds. So the week and day of a moment, and the moment a given wall-clock time falls on, are worked out for a named zone, not the browser's.

export interface Parts {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number;
  minute: number;
}

export interface Day {
  year: number;
  month: number; // 1-12
  day: number;
  key: string; // YYYY-MM-DD, which sorts as dates do
  inMonth: boolean;
  weekday: number; // 0 = Sunday
}

export interface TripLike {
  id: string;
  start: number; // UTC seconds
  end: number;
}

export interface Segment<T extends TripLike> {
  trip: T;
  startCol: number; // 0-6, within the week
  endCol: number; // inclusive
  lane: number;
  continuesBefore: boolean; // the trip began in an earlier week
  continuesAfter: boolean; // and goes on into the next
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });
    formatters.set(timeZone, f);
  }
  return f;
}

/** The wall-clock reading in `timeZone` at a moment given in UTC seconds. */
export function zonedParts(epochSeconds: number, timeZone: string): Parts {
  const out: Record<string, number> = {};
  for (const part of formatter(timeZone).formatToParts(new Date(epochSeconds * 1000))) {
    if (part.type !== "literal") out[part.type] = Number(part.value);
  }
  return { year: out.year!, month: out.month!, day: out.day!, hour: out.hour! % 24, minute: out.minute! };
}

/** The moment (UTC seconds) at which the clocks in `timeZone` read the given wall-clock time. Where a clock change makes that time happen twice or not at all, the later or the
 *  next valid reading is taken. */
export function zonedToEpoch(year: number, month: number, day: number, hour: number, minute: number, timeZone: string): number {
  const wanted = Date.UTC(year, month - 1, day, hour, minute) / 1000;
  let guess = wanted;
  for (let i = 0; i < 3; i++) {
    const p = zonedParts(guess, timeZone);
    const shown = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) / 1000;
    const error = shown - wanted;
    if (error === 0) return guess;
    guess -= error;
  }
  return guess;
}

export const dayKey = (year: number, month: number, day: number): string => `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

/** The calendar date, in the zone, of a moment. */
export function dayOf(epochSeconds: number, timeZone: string): string {
  const p = zonedParts(epochSeconds, timeZone);
  return dayKey(p.year, p.month, p.day);
}

export function addDays(year: number, month: number, day: number, n: number): { year: number; month: number; day: number } {
  const d = new Date(Date.UTC(year, month - 1, day + n));
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

export function addMonths(year: number, month: number, n: number): { year: number; month: number } {
  const index = year * 12 + (month - 1) + n;
  return { year: Math.floor(index / 12), month: (index % 12 + 12) % 12 + 1 };
}

/** The weeks that show a month: whole weeks from the one holding the 1st to the one holding the last day (4 to 6 rows). `weekStart` 0 is Sunday, 1 Monday. */
export function monthGrid(year: number, month: number, weekStart = 0): Day[][] {
  const first = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const lead = (first - weekStart + 7) % 7;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const rows = Math.ceil((lead + daysInMonth) / 7);
  const weeks: Day[][] = [];
  for (let r = 0; r < rows; r++) {
    const week: Day[] = [];
    for (let c = 0; c < 7; c++) {
      const d = addDays(year, month, 1, r * 7 + c - lead);
      week.push({ ...d, key: dayKey(d.year, d.month, d.day), inMonth: d.month === month, weekday: (weekStart + c) % 7 });
    }
    weeks.push(week);
  }
  return weeks;
}

/** [start of the first day, start of the day after the last] of the grid, as UTC seconds: what to ask the server for. */
export function gridRange(weeks: Day[][], timeZone: string): [number, number] {
  const first = weeks[0]![0]!;
  const last = weeks[weeks.length - 1]![6]!;
  const after = addDays(last.year, last.month, last.day, 1);
  return [zonedToEpoch(first.year, first.month, first.day, 0, 0, timeZone), zonedToEpoch(after.year, after.month, after.day, 0, 0, timeZone)];
}

/** The date a trip ends on: its last minute, so a trip that ends exactly at midnight does not spill a sliver into the next day. */
function lastDay(end: number, timeZone: string): string {
  return dayOf(end - 1, timeZone);
}

/** Lay one week's trips out as bars: each trip is one bar across the days of the week it covers, stacked in lanes so bars on the same day never share a row. */
export function layoutWeek<T extends TripLike>(week: Day[], trips: T[], timeZone: string): Segment<T>[] {
  const keys = week.map((d) => d.key);
  const weekFirst = keys[0]!;
  const weekLast = keys[6]!;
  const segments: Omit<Segment<T>, "lane">[] = [];
  for (const trip of trips) {
    const from = dayOf(trip.start, timeZone);
    const to = lastDay(trip.end, timeZone);
    if (to < weekFirst || from > weekLast) continue;
    const startCol = from < weekFirst ? 0 : keys.indexOf(from);
    const endCol = to > weekLast ? 6 : keys.indexOf(to);
    if (startCol < 0 || endCol < 0) continue;
    segments.push({ trip, startCol, endCol, continuesBefore: from < weekFirst, continuesAfter: to > weekLast });
  }
  segments.sort((a, b) => a.startCol - b.startCol || b.endCol - b.startCol - (a.endCol - a.startCol) || a.trip.start - b.trip.start || a.trip.id.localeCompare(b.trip.id));
  const laneEnds: number[] = []; // the last column each lane is used up to
  return segments.map((s) => {
    let lane = laneEnds.findIndex((end) => end < s.startCol);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = s.endCol;
    return { ...s, lane };
  });
}

/** How many bars beyond `visibleLanes` fall on each of the week's seven days. */
export function hiddenPerDay<T extends TripLike>(segments: Segment<T>[], visibleLanes: number): number[] {
  const counts = [0, 0, 0, 0, 0, 0, 0];
  for (const s of segments) {
    if (s.lane < visibleLanes) continue;
    for (let c = s.startCol; c <= s.endCol; c++) counts[c]!++;
  }
  return counts;
}

export function formatTime(epochSeconds: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(epochSeconds * 1000)).replace(/\s*AM$/, "a").replace(/\s*PM$/, "p");
}

export function formatWhen(start: number, end: number, timeZone: string): string {
  const date = (t: number) => new Intl.DateTimeFormat("en-US", { timeZone, weekday: "short", month: "short", day: "numeric" }).format(new Date(t * 1000));
  const time = (t: number) => new Intl.DateTimeFormat("en-US", { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(t * 1000)).replace(/\s/g, " ");     // newer engines put a narrow no-break space before AM/PM
  return dayOf(start, timeZone) === lastDay(end, timeZone) ? `${date(start)}, ${time(start)} to ${time(end)}` : `${date(start)} ${time(start)} to ${date(end)} ${time(end)}`;
}

export function monthTitle(year: number, month: number): string {
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", year: "numeric" }).format(new Date(Date.UTC(year, month - 1, 1)));
}

/** The value of a <input type="datetime-local"> for a moment, read in the boat's zone ("2026-11-20T09:00"). */
export function toLocalInput(epochSeconds: number, timeZone: string): string {
  const p = zonedParts(epochSeconds, timeZone);
  return `${dayKey(p.year, p.month, p.day)}T${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
}

/** The moment a <input type="datetime-local"> value means in the boat's zone, or null when it is not a complete date and time. */
export function fromLocalInput(value: string, timeZone: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!m) return null;
  return zonedToEpoch(Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4]), Number(m[5]), timeZone);
}

export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
