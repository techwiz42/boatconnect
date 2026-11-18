import { describe, expect, it } from "vitest";
import { fitWithin } from "./photo";

describe("fitWithin", () => {
  it("scales the longest side down to the limit and keeps the shape", () => {
    expect(fitWithin(4000, 3000, 1200)).toEqual({ width: 1200, height: 900 });
    expect(fitWithin(3000, 4000, 1200)).toEqual({ width: 900, height: 1200 });
  });

  it("never enlarges a small picture", () => {
    expect(fitWithin(300, 200, 1200)).toEqual({ width: 300, height: 200 });
    expect(fitWithin(1200, 1200, 1200)).toEqual({ width: 1200, height: 1200 });
  });

  it("never produces a zero side for a very thin picture", () => {
    expect(fitWithin(100000, 10, 1200)).toEqual({ width: 1200, height: 1 });
  });
});
