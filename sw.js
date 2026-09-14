// Service worker карты (этап 3 плана 15.09.2026, «го» куратора).
//
// Зачем. GitHub Pages отдаёт всё с Cache-Control: max-age=600: через десять
// минут после захода браузер переспрашивает сервер о каждом файле заново -
// сотни обращений, на 3G это секунды до первого кадра, а второй заход стоит
// почти как первый. Здесь свой кэш: библиотеки, шим, шрифты, свои тайлы
// подложки, срезы и топология линии времени, фронт, пакет старта - всё
// СВОЁ (тот же сайт) отдаётся из кэша, если уже лежит там; второй заход
// открывается без сети.
//
// Как не показать вчерашнюю карту после пересборки. Имя кэша включает
// версию данных из data/version.json (её пишет tools/build_start_bundle.py:
// хеш манифестов и штампов сборки). При каждом открытии страницы воркер
// сперва спрашивает сервер о версии (крошечный файл, без кэша); сменилась -
// старый кэш стирается целиком и данные едут с сервера. Сама страница
// (index.html) и version.json всегда сперва с сервера, из кэша только без
// сети. Так F5 после пересборки видит новое, как и раньше.
//
// Библиотеки (vendor/) и шим (ee-shim.js) отдаются из кэша сразу, а
// свежая копия подтягивается следом («stale-while-revalidate»): правка шима
// без пересборки данных доезжает со второго открытия, версия данных тут ни
// при чём. Чужие адреса (tiles.openfreemap.org и прочие) воркер не трогает.
// Ответы крупнее LIMIT (полные срезы 1991 года по 6 МБ) в кэш не кладутся.
'use strict';
const PREFIX = 'imperium-map-';
const META = PREFIX + 'meta';
const LIMIT = 4 * 1048576;
const VERSION_URL = 'data/version.json';
let version = null;                       // текущая версия данных

async function readVersion() {
  if (version) return version;
  try {
    const c = await caches.open(META);
    const r = await c.match('version');
    if (r) version = await r.text();
  } catch (e) {}
  return version;
}
async function setVersion(v) {
  version = v;
  const c = await caches.open(META);
  await c.put('version', new Response(v));
}
async function checkVersion() {
  // Сперва сервер: сменилась - выкинуть старые кэши. Нет сети - живём с тем,
  // что есть.
  let fresh = null;
  try {
    const r = await fetch(VERSION_URL, {cache: 'no-store'});
    if (r.ok) fresh = String((await r.json()).version || '');
  } catch (e) {}
  if (!fresh) return await readVersion();
  const cur = await readVersion();
  if (fresh !== cur) {
    const names = await caches.keys();
    await Promise.all(names.filter(n => n.startsWith(PREFIX) && n !== META && n !== PREFIX + 'code' && n !== PREFIX + fresh)
                           .map(n => caches.delete(n)));
    await setVersion(fresh);
  }
  return fresh;
}
function dataCacheName(v) { return PREFIX + (v || 'unversioned'); }

self.addEventListener('install', e => {
  e.waitUntil((async () => { await checkVersion(); await self.skipWaiting(); })());
});
self.addEventListener('activate', e => {
  e.waitUntil((async () => { await checkVersion(); await self.clients.claim(); })());
});

const sameOrigin = url => url.origin === self.location.origin;
const isPage = (req, url) => req.mode === 'navigate' || url.pathname.endsWith('/') || url.pathname.endsWith('.html');
const isVersion = url => url.pathname.endsWith('/' + VERSION_URL) || url.pathname.endsWith(VERSION_URL);
// Что кладём в кэш: данные - по версии; библиотеки и шим - с обновлением следом.
const isData = url => /\/data\//.test(url.pathname) && !isVersion(url);
const isCode = url => /\/vendor\/|\/ee-shim\.js$/.test(url.pathname);

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (!sameOrigin(url)) return;            // чужое - мимо воркера
  if (isPage(req, url) || isVersion(url)) {
    // страница: сперва сервер (и заодно проверка версии данных), из кэша только без сети
    e.respondWith((async () => {
      await checkVersion();
      try {
        const r = await fetch(req);
        if (r.ok && isPage(req, url)) {
          const c = await caches.open(dataCacheName(await readVersion()));
          c.put(req, r.clone()).catch(() => {});
        }
        return r;
      } catch (err) {
        const c = await caches.open(dataCacheName(await readVersion()));
        const hit = await c.match(req, {ignoreSearch: true});
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }
  if (isCode(url)) {
    e.respondWith((async () => {
      const c = await caches.open(PREFIX + 'code');
      const hit = await c.match(req);
      const refresh = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()).catch(() => {}); return r; });
      if (hit) { refresh.catch(() => {}); return hit; }
      return refresh;
    })());
    return;
  }
  if (!isData(url)) return;
  e.respondWith((async () => {
    const name = dataCacheName(await readVersion());
    const c = await caches.open(name);
    const hit = await c.match(req);
    if (hit) return hit;
    const r = await fetch(req);
    if (r.ok && r.status === 200) {
      const len = +(r.headers.get('content-length') || 0);
      if (!len || len <= LIMIT) c.put(req, r.clone()).catch(() => {});
    }
    return r;
  })());
});
