/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy /api/* through the Next.js server to the backend instead of
  // having the browser call it directly -- keeps frontend/backend on the
  // same origin (no CORS, no client-side guessing of the backend's URL,
  // which breaks under forwarded/proxied origins like Codespaces). Read at
  // request time, not build time, so it also works when this image is
  // built once and run in different environments.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.INTERNAL_API_URL || "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
