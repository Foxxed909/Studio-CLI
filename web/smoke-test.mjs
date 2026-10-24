import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const server = readFileSync(new URL("./server.js", import.meta.url), "utf8");
const pricing = readFileSync(new URL("./public/pricing.html", import.meta.url), "utf8");
const inbox = readFileSync(new URL("./public/inbox.html", import.meta.url), "utf8");
const extras = readFileSync(new URL("./public/studio-extras.js", import.meta.url), "utf8");
const index = readFileSync(new URL("./public/index.html", import.meta.url), "utf8");
const vercel = JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("./public/manifest.json", import.meta.url), "utf8"));
const polish = readFileSync(new URL("./public/stage-polish.css", import.meta.url), "utf8");
const mobileRuntime = readFileSync(new URL("./public/mobile-runtime.js", import.meta.url), "utf8");
const serviceWorker = readFileSync(new URL("./public/service-worker.js", import.meta.url), "utf8");
const packageJson = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const studioData = readFileSync(new URL("../studio/data.py", import.meta.url), "utf8");

assert.equal(server.includes("ZERO-2026"), false, "server must not contain the legacy admin secret");
assert.equal(inbox.includes("ZERO-2026"), false, "inbox must not contain the legacy admin secret");
assert.equal(extras.includes("ZERO-2026"), false, "extras must not contain the legacy admin secret");
assert.equal(server.includes("subscription.json"), false, "hosted subscriptions must not use local JSON persistence");
assert.equal(server.includes("beta_seats.json"), false, "beta seats must not use local JSON persistence");
assert.equal(server.includes("/api/community/stream"), false, "community must not rely on long-lived serverless SSE");
assert.equal(index.includes("/api/community/stream"), false, "community client must not rely on long-lived SSE");
assert.match(index, /\/api\/community\/history/, "community client should poll durable history");
assert.match(pricing, /billing:\s*_annualMode\s*\?\s*['"]annual['"]\s*:\s*['"]monthly['"]/, "annual checkout choice must reach the server");
assert.match(pricing, /Authorization:\s*['"]Bearer ['"]\s*\+\s*token/, "checkout must send the Supabase session");
assert.match(server, /subscription_data:\s*\{\s*metadata\s*\}/, "Stripe subscription metadata must retain plan identity");
assert.match(server, /resolvePlanForEmail/, "Stripe-backed plan resolution must exist");
assert.match(server, /requestOpenRouterKey/, "BYOK must be distinguished from account JWTs");
assert.ok(vercel.builds?.[0]?.config?.maxDuration >= 240, "Vercel maxDuration must cover upstream AI timeout");


const NEMOTRON_ULTRA = "nvidia/nemotron-3-ultra-550b-a55b:free";
assert.ok(server.includes(NEMOTRON_ULTRA), "server model registry must include Nemotron 3 Ultra");
assert.ok(index.includes(NEMOTRON_ULTRA), "Stage model picker must include Nemotron 3 Ultra");
assert.ok(studioData.includes(NEMOTRON_ULTRA), "CLI free plan must include Nemotron 3 Ultra");

assert.equal(manifest.display, "standalone", "PWA must install in standalone mode");
assert.equal(manifest.orientation, "any", "PWA must support portrait and landscape");
assert.ok(manifest.icons?.some((icon) => icon.purpose === "maskable"), "PWA must provide a maskable Android icon");
assert.match(index, /viewport-fit=cover/, "Stage must opt into iPhone/Android safe areas");
assert.ok(index.lastIndexOf("/stage-polish.css") > index.lastIndexOf("</style>"),
  "polish stylesheet must load after core Stage styles");
assert.match(polish, /safe-area-inset-bottom/, "mobile layout must respect safe-area insets");
assert.match(polish, /pointer:coarse/, "mobile layout must adapt to touch input");
assert.match(polish, /prefers-reduced-motion:reduce/, "Stage must honor reduced-motion preferences");
assert.match(mobileRuntime, /visualViewport/, "mobile runtime must handle software-keyboard viewport changes");
assert.match(mobileRuntime, /beforeinstallprompt/, "Android PWA install flow must be supported");
assert.match(serviceWorker, /url\.pathname\.startsWith\("\/api\/"\)/,
  "service worker must keep API traffic network-only");
assert.equal(packageJson.dependencies?.["@vercel/connect"], "^2.5.2",
  "Vercel Connect SDK must be pinned in Stage dependencies");
assert.match(server, /app\.get\("\/api\/connectors", requireAuth/,
  "connector catalog must require Studio authentication");
assert.match(server, /app\.post\("\/api\/connectors\/:provider\/authorize", requireAuth/,
  "connector authorization must require Studio authentication");
assert.equal(server.includes("providerToken"), false, "browser-facing connector API must not expose provider token fields");

console.log("Studio Stage production smoke checks passed.");
