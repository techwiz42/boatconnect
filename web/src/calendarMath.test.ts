import { describe, expect, it } from "vitest";
import { addMonths, dayOf, formatTime, formatWhen, fromLocalInput, gridRange, hiddenPerDay, layoutWeek, monthGrid, toLocalInput, zonedParts, zonedToEpoch } from "./calendarMath";

const LA = "America/Los_Angeles";
const trip = (id: string, start: number, end: number) => ({ id, start, end });
const at = (y: number, mo: number, d: number, h = 0, mi = 0, tz = LA) => zonedToEpoch(y, mo, d, h, mi, tz);

describe("time zones", () => {
  it("reads the wall clock of a zone", () => {
    expect(zonedParts(Date.UTC(2026, 6, 4, 19, 30) / 1000, LA)).toEqual({ year: 2026, month: 7, day: 4, hour: 12, minute: 30 });          // PDT, UTC-7
    expect(zonedParts(Date.UTC(2026, 11, 4, 19, 30) / 1000, LA)).toEqual({ year: 2026, month: 12, day: 4, hour: 11, minute: 30 });         // PST, UTC-8
  });

  it("converts a wall-clock time back to the moment, either side of a clock change", () => {
    for (const [y, m, d, h] of [[2026, 7, 4, 12], [2026, 12, 4, 11], [2026, 3, 8, 12], [2026, 11, 1, 12]] as const) {
      expect(zonedParts(at(y, m, d, h), LA)).toMatchObject({ year: y, month: m, day: d, hour: h, minute: 0 });
    }
  });

  it("puts midnight where the zone says, not the browser", () => {
    expect(at(2026, 7, 4, 0, 0, "UTC")).toBe(Date.UTC(2026, 6, 4) / 1000);
    expect(at(2026, 7, 4, 0, 0, LA)).toBe(Date.UTC(2026, 6, 4, 7) / 1000);
    expect(at(2026, 7, 4, 0, 0, "Pacific/Auckland")).toBe(Date.UTC(2026, 6, 3, 12) / 1000);
  });

  it("names the day of a moment in the zone", () => {
    expect(dayOf(Date.UTC(2026, 6, 5, 3, 0) / 1000, LA)).toBe("2026-07-04");                   // still Saturday evening in Los Angeles
    expect(dayOf(Date.UTC(2026, 6, 5, 3, 0) / 1000, "UTC")).toBe("2026-07-05");
  });

  it("round-trips a datetime-local value", () => {
    expect(fromLocalInput("2026-11-20T09:00", LA)).toBe(at(2026, 11, 20, 9));
    expect(toLocalInput(at(2026, 11, 20, 9), LA)).toBe("2026-11-20T09:00");
    expect(fromLocalInput("2026-11-20", LA)).toBeNull();
    expect(fromLocalInput("", LA)).toBeNull();
  });

  it("shows times briefly and ranges in words", () => {
    expect(formatTime(at(2026, 11, 20, 9), LA)).toBe("9:00a");
    expect(formatTime(at(2026, 11, 20, 14, 30), LA)).toBe("2:30p");
    expect(formatWhen(at(2026, 11, 20, 9), at(2026, 11, 20, 17), LA)).toBe("Fri, Nov 20, 9:00 AM to 5:00 PM");
    expect(formatWhen(at(2026, 11, 20, 9), at(2026, 11, 22, 17), LA)).toBe("Fri, Nov 20 9:00 AM to Sun, Nov 22 5:00 PM");
  });
});

describe("month grid", () => {
  it("shows whole weeks, from the week holding the 1st to the week holding the last day", () => {
    const grid = monthGrid(2026, 11);                                 // November 2026 starts on a Sunday and has 30 days
    expect(grid.length).toBe(5);
    expect(grid[0]![0]!.key).toBe("2026-11-01");
    expect(grid[4]![6]!.key).toBe("2026-12-05");
    expect(grid.flat().filter((d) => d.inMonth).length).toBe(30);
    expect(grid.every((w) => w.length === 7)).toBe(true);
  });

  it("starts the week on Monday when asked", () => {
    const grid = monthGrid(2026, 11, 1);
    expect(grid[0]![0]!.key).toBe("2026-10-26");
    expect(grid[0]![0]!.weekday).toBe(1);
    expect(grid[0]![6]!.weekday).toBe(0);
  });

  it("needs six rows when the month straddles them, and four when it fits exactly", () => {
    expect(monthGrid(2026, 8).length).toBe(6);                        // August 2026: starts on a Saturday, 31 days
    expect(monthGrid(2026, 2).length).toBe(4);                        // February 2026: starts on a Sunday, 28 days
  });

  it("steps by months across a year end", () => {
    expect(addMonths(2026, 12, 1)).toEqual({ year: 2027, month: 1 });
    expect(addMonths(2026, 1, -1)).toEqual({ year: 2025, month: 12 });
    expect(addMonths(2026, 6, 0)).toEqual({ year: 2026, month: 6 });
  });

  it("gives the range of moments to ask the server for", () => {
    const [from, to] = gridRange(monthGrid(2026, 11), LA);
    expect(from).toBe(at(2026, 11, 1));
    expect(to).toBe(at(2026, 12, 6));
  });
});

describe("laying trips out as bars", () => {
  const week = monthGrid(2026, 11)[1]!;                               // Nov 8 - Nov 14, 2026

  it("puts a one-day trip in its column", () => {
    const [s] = layoutWeek(week, [trip("a", at(2026, 11, 10, 9), at(2026, 11, 10, 17))], LA);
    expect(s).toMatchObject({ startCol: 2, endCol: 2, lane: 0, continuesBefore: false, continuesAfter: false });
  });

  it("stretches a multi-day trip across its days", () => {
    const [s] = layoutWeek(week, [trip("a", at(2026, 11, 9, 18), at(2026, 11, 12, 10))], LA);
    expect([s!.startCol, s!.endCol]).toEqual([1, 4]);
  });

  it("clips a trip that runs in from the last week and out into the next", () => {
    const [s] = layoutWeek(week, [trip("a", at(2026, 11, 5, 9), at(2026, 11, 20, 9))], LA);
    expect(s).toMatchObject({ startCol: 0, endCol: 6, continuesBefore: true, continuesAfter: true });
  });

  it("ignores trips outside the week", () => {
    expect(layoutWeek(week, [trip("a", at(2026, 11, 1, 9), at(2026, 11, 2, 9)), trip("b", at(2026, 11, 15, 9), at(2026, 11, 16, 9))], LA)).toEqual([]);
  });

  it("does not spill a trip that ends exactly at midnight into the next day", () => {
    const [s] = layoutWeek(week, [trip("a", at(2026, 11, 9, 20), at(2026, 11, 10, 0))], LA);
    expect([s!.startCol, s!.endCol]).toEqual([1, 1]);
  });

  it("uses the zone's days, not UTC's: a trip that ends at 5pm on Saturday evening belongs to Saturday", () => {
    const [s] = layoutWeek(week, [trip("a", at(2026, 11, 14, 14), at(2026, 11, 14, 19))], LA);       // 19:00 PST is 03:00 UTC on the 15th
    expect([s!.startCol, s!.endCol]).toEqual([6, 6]);
  });

  it("stacks trips that share a day and reuses a lane once it is free", () => {
    const out = layoutWeek(week, [
      trip("long", at(2026, 11, 8, 9), at(2026, 11, 11, 9)),                       // Sun-Wed
      trip("mid", at(2026, 11, 10, 9), at(2026, 11, 10, 17)),                      // Tue, shares Tue and Wed with "long"
      trip("late", at(2026, 11, 12, 9), at(2026, 11, 12, 17)),                     // Thu, after both
    ], LA);
    expect(Object.fromEntries(out.map((s) => [s.trip.id, s.lane]))).toEqual({ long: 0, mid: 1, late: 0 });
  });

  it("counts what does not fit in the visible lanes, per day", () => {
    const trips = ["a", "b", "c", "d"].map((id, i) => trip(id, at(2026, 11, 10, 8 + i), at(2026, 11, 10, 8 + i, 30)));
    const out = layoutWeek(week, trips, LA);
    expect(out.map((s) => s.lane)).toEqual([0, 1, 2, 3]);
    expect(hiddenPerDay(out, 3)).toEqual([0, 0, 1, 0, 0, 0, 0]);
    expect(hiddenPerDay(out, 4)).toEqual([0, 0, 0, 0, 0, 0, 0]);
  });
});
