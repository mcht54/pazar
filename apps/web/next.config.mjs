import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Depo kökünde ayrı bir package-lock.json var; Next.js'in yanlış çalışma kökü seçmemesi için sabitlenir.
  turbopack: { root: here },
  agentRules: false,
};

export default nextConfig;
