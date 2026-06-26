import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Image Docker légère : runtime autonome (.next/standalone), sans node_modules complet.
  output: "standalone",
  // better-sqlite3 = module natif → ne pas le bundler (chargé depuis node_modules tracé).
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
