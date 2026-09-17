import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  transpilePackages: ["@gisul/voice-ui"],
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
