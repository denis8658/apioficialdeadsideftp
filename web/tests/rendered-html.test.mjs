import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("https://dashboard.example/", { headers: { accept: "text/html", host: "dashboard.example", "x-forwarded-host": "dashboard.example", "x-forwarded-proto": "https" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Deadside dashboard shell and production metadata", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Deadside Command Center<\/title>/i);
  assert.match(html, /DEADSIDE/);
  assert.match(html, /COMMAND CENTER/);
  assert.match(html, /Mapa tático/);
  assert.match(html, /Eventos ao vivo/);
  assert.match(html, /https:\/\/dashboard\.example\/og\.png/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("contains the API proxy, live-data views and social preview", async () => {
  const [dashboard, proxy, packageJson] = await Promise.all([
    readFile(new URL("../app/dashboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/proxy/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(dashboard, /map\/entities/);
  assert.match(dashboard, /kills\/leaderboard/);
  assert.match(dashboard, /new WebSocket/);
  assert.match(dashboard, /API Explorer/);
  assert.match(proxy, /DEADSIDE_API_URL/);
  assert.match(proxy, /safePosts/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await access(new URL("../public/og.png", import.meta.url));
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
