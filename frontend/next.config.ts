import type { NextConfig } from "next";

// The browser talks to the API through this server at the same paths (/v1/...), so the API's
// refresh cookie (Path=/v1/auth, SameSite=Strict) is first-party and needs no CORS.
const API_URL = process.env.KHATAIQ_API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  reactStrictMode: true,
  images: { unoptimized: true },
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${API_URL}/v1/:path*` },
      { source: "/healthz", destination: `${API_URL}/healthz` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default config;
