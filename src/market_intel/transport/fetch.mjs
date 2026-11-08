// Optional compatibility transport. Only fixed official endpoints are allowed.
const endpoints = {
  fed: "https://www.federalreserve.gov/feeds/press_all.xml",
  nbs: "https://www.stats.gov.cn/sj/zxfb/",
};
const url = endpoints[process.argv[2]];
if (!url) throw new Error("unknown_source");
const maxBytes = 5 * 1024 * 1024;
const response = await fetch(url, {
  headers: {"User-Agent": "MarketIntelResearch/0.1 (low-frequency internal metadata reader)"},
  redirect: "error",
  signal: AbortSignal.timeout(20000),
});
if (!response.ok) throw new Error(`source_http_${response.status}`);
const reader = response.body.getReader();
const chunks = [];
let size = 0;
while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  size += value.byteLength;
  if (size > maxBytes) { await reader.cancel(); throw new Error("source_too_large"); }
  chunks.push(Buffer.from(value));
}
process.stdout.write(JSON.stringify({
  data_base64: Buffer.concat(chunks).toString("base64"),
  response: {url, final_url: response.url, http_status: response.status,
             fetched_at: new Date().toISOString(), transport: "node-verified-https"},
}));
