/**
 * mock/serve.js —— 静态文件服务（零依赖 node:http）
 * ------------------------------------------------------------
 * 用途：本地起前端。ES module 不能用 file:// 打开（CORS），
 *       所以需要一个静态服务。
 *
 *   node mock/serve.js            → http://127.0.0.1:5173
 *   PORT=8080 node mock/serve.js  → 换端口
 *
 * 带 mock 后端联调（验证真实 HTTP + SSE）：
 *   1) node mock/server.js               （8788）
 *   2) node mock/serve.js
 *   3) 打开 http://127.0.0.1:5173/?mock=0&base=http://127.0.0.1:8788
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const PORT = Number(process.env.PORT || 5173);
const HOST = '127.0.0.1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.md': 'text/markdown; charset=utf-8',
};

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, `http://${req.headers.host}`).pathname);
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
    });
    fs.createReadStream(file).pipe(res);
  });
});

server.listen(PORT, HOST, () => {
  console.log('[serve] paper-agent-web 已启动');
  console.log(`[serve]   http://${HOST}:${PORT}`);
  console.log(`[serve]   根目录 ${ROOT}`);
  console.log('[serve]   提示：直接双击 index.html（file://）会被 CORS 拦住，请用本服务。');
});