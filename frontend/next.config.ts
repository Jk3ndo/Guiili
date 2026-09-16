import type { NextConfig } from "next";

// En production, frontend (Vercel) et backend (Cloud Run) sont deux domaines
// distincts (vercel.app / run.app) — le cookie de session (SameSite=Lax) ne
// serait alors jamais envoye sur les appels fetch() du navigateur vers le
// backend, seulement sur une vraie navigation. Ce proxy fait que le
// navigateur ne parle jamais qu'a l'origine du frontend : les appels API et
// le callback OAuth passent tous par ce rewrite, donc le cookie qu'ils
// posent est scope au frontend et suit les regles same-site normalement.
// Sans effet en dev local (127.0.0.1 des deux cotes = deja same-site).
const BACKEND_URL = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8020";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
