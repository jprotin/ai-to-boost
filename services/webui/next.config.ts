import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Image Docker légère : runtime autonome (.next/standalone), sans node_modules complet.
  output: "standalone",
};

export default nextConfig;
