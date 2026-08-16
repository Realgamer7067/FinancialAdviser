// Proxies /api/* to the backend, server-side, on every request. Keeps the
// browser talking to a single same-origin host (no CORS, no client-side
// guessing of the backend's URL -- which breaks under forwarded/proxied
// origins like Codespaces). Deliberately a Route Handler and not a
// next.config.js rewrite: rewrites() is evaluated once at `next build` time,
// so INTERNAL_API_URL would need to be known at image-build time too --
// this reads it fresh on every request instead, so one built image works
// unchanged across Docker, Codespaces, or anywhere else.

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "content-length",
  "host",
]);

async function proxy(req: Request, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const backendBase = process.env.INTERNAL_API_URL || "http://localhost:8000";
  const { path } = await context.params;
  const url = new URL(req.url);
  const target = `${backendBase}/api/${path.join("/")}${url.search}`;

  const headers = new Headers(req.headers);
  for (const name of HOP_BY_HOP_HEADERS) headers.delete(name);

  const res = await fetch(target, {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer(),
    redirect: "manual",
  });

  const resHeaders = new Headers(res.headers);
  for (const name of HOP_BY_HOP_HEADERS) resHeaders.delete(name);

  return new Response(res.body, { status: res.status, headers: resHeaders });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
