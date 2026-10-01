import type { NextConfig } from "next";

const isExport = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  // "standalone" is what the `production` stage in the Dockerfile needs.
  // `make aws-deploy-frontend` sets NEXT_OUTPUT=export instead, to bundle the
  // static files into the Lambda image.
  output: isExport ? "export" : "standalone",
  // A folder per route (meetings/new/index.html) is served at a clean URL by
  // any static host, with no rewrite from /meetings/new to meetings/new.html.
  trailingSlash: isExport,
};

export default nextConfig;
