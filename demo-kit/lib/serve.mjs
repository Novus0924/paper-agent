/**
 * demo-kit/lib/serve.mjs — 参数化静态文件服务（零依赖 node:http）
 * ------------------------------------------------------------
 * 与 web/mock/serve.js 等价，但**根目录可配**（web/mock/serve.js 的根被写死为 web/）。
 * demo-kit 需要指向 `演示原型/`（mock 主展示面）或 `web/`（live/fake 前端），
 * 故抽一个通用的。
 *
 *   PA_SERVE_ROOT=<目录> PORT=5173 node lib/serve.mjs
 *   默认：PA_SERVE_ROOT = <repo>/演示原型 ，PORT = 5173
 *
 * 零第三方依赖：只用 node:http / node:fs / node:path / node:url。
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// 根目录：优先 PA_SERVE_ROOT；否则在"仓库内 演示原型/"与"仓库上一级 演示原型/"里挑一个存在的
function pickRoot() {
  if (process.env.PA_SERVE_ROOT) return path.resolve(process.env.PA_SERVE_ROOT);
  const cands = [
    path.resolve(__dirname, '..', '..', '演示原型'),
    path.resolve(__dirname, '..', '..', '..', '演示原型'),
  ];
  for (const c of cands) {
    try { if (fs.statSync(c).isDirectory()) return c; } catch { /* 不存在 */ }
  }
  return cands[0];
}
const ROOT = pickRoot();
const PORT = Number(process.env.PORT || 5173);
const HOST = '127.0.0.1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jsonl': 'application/x-ndjson; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.md': 'text/markdown; charset=utf-8',
};

const server = http.createServer((req, res) => {
  let p;
  try {
    p = decodeURIComponent(new URL(req.url, `http://${req.headers.host}`).pathname);
  } catch {
    res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
    return res.end('400 非法请求路径');
  }
  if (p === '/') p = '/index.html';

  // 目录穿越防护：解析后必须仍在 ROOT 内
  const file = path.resolve(ROOT, '.' + p);
  if (!file.startsWith(ROOT)) {
    res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    return res.end('403 越界访问已阻止');
  }

  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end(`404 ${p}`);
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Content-Length': st.size,
      'Cache-Control': 'no-cache',
      'Access-Control-Allow-Origin': '*',
    });
    fs.createReadStream(file).pipe(res);
  });
});

server.listen(PORT, HOST, () => {
  console.log('[demo-kit/serve] 静态服务已启动');
  console.log(`[demo-kit/serve]   http://${HOST}:${PORT}`);
  console.log(`[demo-kit/serve]   根目录 ${ROOT}`);
});
