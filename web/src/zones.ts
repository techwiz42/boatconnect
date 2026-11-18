/** The time zone names a browser knows, for the datalist of a time-zone field; a short list where it cannot say. */
export function zones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "Europe/London", "UTC"];
  }
}
