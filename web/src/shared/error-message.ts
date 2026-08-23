export function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.trim().length > 0) {
    const message = error.message.trim();
    try {
      const parsed = JSON.parse(message) as { detail?: unknown };
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        return parsed.detail.trim();
      }
    } catch {
      // Non-JSON errors are already user-readable.
    }
    return message;
  }
  return 'Request failed. Check the form values and service status.';
}
