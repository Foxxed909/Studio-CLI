import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const server = readFileSync(new URL("./server.js", import.meta.url), "utf8");
const pricing = readFileSync(new URL("./public/pricing.html", import.meta.url), "utf8");
const inbox = readFileSync(new URL("./public/inbox.html", import.meta.url), "utf8");
const extras = readFileSync(new URL("./public/studio-extras.js", import.meta.url), "utf8");
const index = readFileSync(new URL("./public/index.html", import.meta.url), "utf8");
const vercel = JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf8"));

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

console.log("Studio Stage production smoke checks passed.");
