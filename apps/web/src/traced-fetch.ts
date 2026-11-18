// Forward W3C context for browser and SSR calls. Sampled requests use the same ID in Tempo.
export const tracedFetch: typeof fetch = (input, init) => {
  const headers = new Headers(init?.headers);
  if (!headers.has("traceparent")) {
    const hex = () => crypto.randomUUID().replaceAll("-", "");
    const id = hex();
    const flags = parseInt(id.slice(0, 4), 16) < 6554 ? "01" : "00";
    headers.set("traceparent", `00-${id}-${hex().slice(0, 16)}-${flags}`);
  }
  return fetch(input, { ...init, headers });
};
