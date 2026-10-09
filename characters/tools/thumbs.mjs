// Renders thumbnail sheets of the population in headless Chromium (same generator code as the gallery).
// Usage: node tools/thumbs.mjs <outDir> [perSheet=60] [parallel=4]
import fs from 'fs';
import { chromium } from 'playwright-core';
const dir = process.argv[2] || 'out/thumbs', per = +(process.argv[3] || 60), par = +(process.argv[4] || 4);
const total = JSON.parse(fs.readFileSync('out/villagers.json')).count;
fs.mkdirSync(dir, { recursive: true });
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const jobs = []; for (let f = 0; f < total; f += per) jobs.push(f);
const logs = [];
async function worker() {
  while (jobs.length) {
    const f = jobs.shift();
    const p = await b.newPage();
    p.on('pageerror', e => console.log('ERR', e.message));
    const t = Date.now();
    await p.goto(`http://localhost:8765/viewer/thumbs.html?from=${f}&to=${Math.min(total, f + per)}`);
    await p.waitForFunction(() => document.title === 'done', null, { timeout: 900000 });
    const r = await p.evaluate(() => window.RESULT);
    fs.writeFileSync(`${dir}/sheet_${String(f / per).padStart(2, '0')}.webp`, Buffer.from(r.url.split(',')[1], 'base64'));
    logs.push(...r.log);
    console.log('sheet', f / per, ((Date.now() - t) / 1000).toFixed(0) + 's');
    await p.close();
  }
}
await Promise.all(Array.from({ length: par }, worker));
await b.close();
logs.sort((a, c) => a.id - c.id);
fs.writeFileSync(`${dir}/thumbs.json`, JSON.stringify({ per, cols: 10, tw: 200, th: 300, log: logs }));
const tris = logs.map(l => l.tris); console.log('tris avg', Math.round(tris.reduce((a, c) => a + c, 0) / tris.length), 'max', Math.max(...tris));
