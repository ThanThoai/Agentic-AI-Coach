/**
 * Normalise an API error response body into a plain string.
 * Handles two formats:
 *   - Custom contract: { error: { message: "..." } }
 *   - FastAPI default: { detail: "..." } or { detail: [{ msg: "..." }] }
 */
export function extractApiMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const b = body as Record<string, unknown>;

  // Custom contract
  const errObj = b.error;
  if (errObj && typeof errObj === "object") {
    const msg = (errObj as Record<string, unknown>).message;
    if (typeof msg === "string" && msg) return msg;
  }

  // FastAPI detail string
  if (typeof b.detail === "string" && b.detail) return b.detail;

  // FastAPI validation array: [{ loc, msg, type }]
  if (Array.isArray(b.detail) && b.detail.length > 0) {
    const first = b.detail[0] as Record<string, unknown>;
    if (typeof first?.msg === "string") return `Validation: ${first.msg}`;
  }

  return fallback;
}
