import { describe, expect, it } from "vitest";
import { fitWithin } from "./images";

describe("fitWithin", () => {
  it("scales the longer side down to the limit and keeps the aspect ratio", () => {
    expect(fitWithin(4000, 3000, 192)).toEqual({ width: 192, height: 144 });
    expect(fitWithin(1080, 1920, 192)).toEqual({ width: 108, height: 192 });
  });

  it("never upscales a small image", () => {
    expect(fitWithin(64, 48, 192)).toEqual({ width: 64, height: 48 });
  });

  it("keeps a very thin image at least one pixel wide", () => {
    expect(fitWithin(10000, 5, 192)).toEqual({ width: 192, height: 1 });
  });

  it("returns zero for an image with no size", () => {
    expect(fitWithin(0, 100, 192)).toEqual({ width: 0, height: 0 });
  });
});
