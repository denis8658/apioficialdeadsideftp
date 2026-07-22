import { NextRequest } from "next/server";

const upstream = (process.env.DEADSIDE_API_URL || "https://apioficialdeadsideftp-production.up.railway.app").replace(/\/$/, "");
const safePosts = [
  /\/ftp\/(test|discover)$/,
  /\/sync\/(run|start|stop)$/,
  /\/map\/(convert|reverse-convert)$/,
];

async function forward(request: NextRequest) {
  const path = request.nextUrl.searchParams.get("path") || "";
  const method = request.method.toUpperCase();
  if (!path.startsWith("/api/v1/") || path.includes("..") || path.includes("://")) {
    return Response.json({ error: "Caminho não permitido" }, { status: 400 });
  }
  if (method !== "GET" && (method !== "POST" || !safePosts.some((rule) => rule.test(path.split("?")[0])))) {
    return Response.json({ error: "Operação não permitida pelo painel" }, { status: 405 });
  }

  const headers = new Headers({ Accept: request.headers.get("accept") || "application/json" });
  let body: ArrayBuffer | undefined;
  if (method === "POST") {
    headers.set("Content-Type", "application/json");
    body = await request.arrayBuffer();
  }
  const response = await fetch(`${upstream}${path}`, {
    method,
    headers,
    body: body && body.byteLength ? body : undefined,
    cache: "no-store",
  });
  const responseHeaders = new Headers();
  responseHeaders.set("Content-Type", response.headers.get("content-type") || "application/octet-stream");
  responseHeaders.set("Cache-Control", path.includes("/maps/mirny/image") ? "public, max-age=86400" : "no-store");
  const requestId = response.headers.get("x-request-id");
  if (requestId) responseHeaders.set("X-Request-ID", requestId);
  return new Response(await response.arrayBuffer(), { status: response.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
