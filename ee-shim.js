// ---- Equal Earth: OpenLayers под личиной MapLibre --------------------------
// 05.09.2026. Куратор: «пусть мир наконец узнает, как Россия на самом деле
// выглядела» - показ переезжает с Web Mercator на равновеликую проекцию
// Equal Earth (резолюция ГА ООН «Correct the Map» от 04.09.2026). MapLibre
// Equal Earth не умеет, OpenLayers умеет через proj4 и переносит векторные
// тайлы OpenFreeMap по вершинам, подписи стоят прямо. Чтобы не переписывать
// 3000 строк index.html, этот файл подставляет объект `maplibregl` с тем же
// набором вызовов, которым пользуется карта (addSource/addLayer/setData/
// jumpTo/fitBounds/on('click')/Popup...), а внутри крутит OpenLayers.
// Разбор граблей проекции и тайлов - ~/tmp/MAP-MATERIALS/loop_2026-09-05_ee/
// (B1_podlozhka.md, B2_prototip.md); прототип - ee.html.
(function () {
'use strict';
const LON0 = 90;            // центральный меридиан: империя посередине, шов 180° уходит в Америку
const MAXLAT = 85;          // выше тайлов Web Mercator нет
const HALF = 20037508.342789244;

// ---- проекции ---------------------------------------------------------------
// Equal Earth на СФЕРЕ (R = 6378137): формула авторов сферическая, прямые
// формулы ниже тоже; proj4 с +datum=WGS84 считал бы через авталическую широту
// эллипсоида и расходился с ними на 20 км.
proj4.defs('EE', `+proj=eqearth +lon_0=${LON0} +x_0=0 +y_0=0 +a=6378137 +b=6378137 +units=m +no_defs +type=crs`);
// Меркатор с центральным меридианом LON0 - сетка исходных тайлов со швом на
// LON0-180, а не на 180° посреди Чукотки (тайл, задевающий шов сетки, при
// пересчёте в исходную проекцию даёт протяжённость во весь мир - полосы).
// СФЕРИЧЕСКИЙ Меркатор, как у тайлов OSM (EPSG:3857): эллипсоидный (+datum=WGS84
// без +a=+b) сдвигал подложку к северу на 0,18° (~20 км) относительно красного -
// найдено 05.09 при замере скорости.
proj4.defs('MERC90', `+proj=merc +lon_0=${LON0} +k=1 +x_0=0 +y_0=0 +a=6378137 +b=6378137 +units=m +nadgrids=@null +no_defs +type=crs`);
ol.proj.register(proj4);
const EE = ol.proj.get('EE'), M = ol.proj.get('MERC90');
const P = proj4('EE'), PM = proj4('MERC90');
const YMAX = P.forward([LON0, MAXLAT])[1];
const XMAX = P.forward([LON0 + 179.999, 0])[0];
EE.setExtent([-XMAX, -YMAX, XMAX, YMAX]);
EE.setWorldExtent([LON0 - 180, -MAXLAT, LON0 + 180, MAXLAT]);
M.setExtent([-HALF, -HALF, HALF, HALF]);
M.setWorldExtent([LON0 - 180, -85.0511, LON0 + 180, 85.0511]);
// Прямые формулы без proj4 (proj4 - 217 мс на 100 тыс. точек, формула - 30):
// каждая вершина каждого тайла проходит через этот пересчёт при загрузке.
const R = 6378137, A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796;
const S3 = Math.sqrt(3) / 2, K3 = 2 * Math.sqrt(3) / 3, D2R = Math.PI / 180, LON0R = LON0 * D2R;
function eeXY(lonR, latR) {                      // Equal Earth (Шаврич, Патерсон, Дженни 2018), сфера
  let lam = lonR - LON0R;
  if (lam > Math.PI) lam -= 2 * Math.PI; else if (lam < -Math.PI) lam += 2 * Math.PI;
  const th = Math.asin(S3 * Math.sin(latR)), t2 = th * th, t6 = t2 * t2 * t2;
  return [R * K3 * lam * Math.cos(th) / (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)),
          R * th * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))];
}
const fwd = c => eeXY(c[0] * D2R, c[1] * D2R);
const mercInvToEE = c => eeXY(c[0] / R + LON0R, 2 * Math.atan(Math.exp(c[1] / R)) - Math.PI / 2);   // MERC90 -> EE
const merc3857ToEE = c => eeXY(c[0] / R, 2 * Math.atan(Math.exp(c[1] / R)) - Math.PI / 2);          // EPSG:3857 -> EE
// Обратный пересчёт с зажимом: угол тайла за овалом мира иначе даёт NaN, и
// OpenLayers считает такой тайл пустым (пусто на обзоре и выше 72° с. ш.).
function inv(c) {
  let x = c[0], y = c[1];
  if (y > YMAX) y = YMAX; else if (y < -YMAX) y = -YMAX;
  const lat = P.inverse([0, y])[1];
  const xe = P.forward([LON0 + 179.999, lat])[0];
  if (x > xe) x = xe; else if (x < -xe) x = -xe;
  const r = P.inverse([x, y]);
  return [r[0], r[1]];
}
// Буфер тайла на шве сетки уходит за ±HALF; без зажима такая вершина улетает
// на другой край мира (полосы через всю карту).
const clampX = x => x > HALF - 1 ? HALF - 1 : (x < 1 - HALF ? 1 - HALF : x);
ol.proj.addCoordinateTransforms('EPSG:4326', EE, fwd, inv);
ol.proj.addCoordinateTransforms('EPSG:3857', EE, merc3857ToEE, c => ol.proj.fromLonLat(inv(c)));
ol.proj.addCoordinateTransforms('EPSG:4326', M, c => PM.forward([c[0], c[1]]), c => PM.inverse([c[0], c[1]]));
ol.proj.addCoordinateTransforms(M, EE, c => mercInvToEE([clampX(c[0]), c[1]]), c => PM.forward(inv(c)));
// Исходные тайлы на зум мельче целевых: рёбра тайла Меркатора после переноса
// вершин в Equal Earth - хорды; чем мельче тайл, тем короче хорда.
const ORIG_SOURCE_Z = ol.VectorTileSource.prototype.getSourceZ_;
// «го» куратора 05.09: до зума 5 (по Меркатору) тайлы на зум мельче - на
// обзоре край большого тайла (прямой отрезок между вершинами) заметно отходит
// от кривого меридиана, и соседние тайлы не сходятся; от зума 5 тайлы уже
// малы, полос нет (кадры B3_frames/srcz_test.png), берём родные - вчетверо
// меньше разбора и пересчёта при движении. ?srcz=N - принудительно.
const SRCZ_Q = new URLSearchParams(location.search).get('srcz');
const NATIVE_FROM = 5;
ol.VectorTileSource.prototype.getSourceZ_ = function (resolution, projection, pixelRatio) {
  const z = ORIG_SOURCE_Z.call(this, resolution, projection, pixelRatio);
  const extra = SRCZ_Q !== null ? +SRCZ_Q : (z < NATIVE_FROM ? 1 : 0);
  return Math.min(z + extra, this.getTileGrid().getMaxZoom());
};

// ---- зум: MapLibre (Меркатор, тайлы 512) <-> OpenLayers (Equal Earth, 256 на z0)
// Один и тот же вид: наземное разрешение равно. У Меркатора оно зависит от
// широты (cos φ), у равновеликой проекции - нет.
const RES0 = (2 * XMAX) / 256;
const zOL = (z, lat) => z + Math.log2(RES0 / (78271.517 * Math.max(0.05, Math.cos(lat * Math.PI / 180))));
const zML = (z, lat) => z - Math.log2(RES0 / (78271.517 * Math.max(0.05, Math.cos(lat * Math.PI / 180))));

const FMT = new ol.GeoJSON({dataProjection: 'EPSG:4326', featureProjection: EE});
const hex = (c, a) => {
  if (typeof c !== 'string') return c;
  if (c[0] === '#' && c.length === 7)
    return `rgba(${parseInt(c.slice(1, 3), 16)},${parseInt(c.slice(3, 5), 16)},${parseInt(c.slice(5, 7), 16)},${a})`;
  return c;
};
function matches(filter, f) {
  if (!filter) return true;
  if (filter[0] === '==' && Array.isArray(filter[1]) && filter[1][0] === 'get') return f.get(filter[1][1]) === filter[2];
  return true;
}

// ---- Крым: подписи подложки по-украински ------------------------------------
// Куратор 05.09.2026: «найди все что есть на русском и замени на украинские
// слова». В тайлах OSM у объектов Крыма name - по-русски, но почти у всех
// есть name:uk (проверено по тайлам z10-12: 980 из 982 мест). Внутри контура
// Крыма (data/crimea_outline.geojson, Natural Earth) подписи берутся из name:uk,
// латиница - транслитерация по постановлению КМУ № 55 от 27.01.2010.
const RU_CLAIM_NAMES = ['Республика Крым', 'Republic of Crimea', 'Республіка Крим', 'Respublika Krym'];
let CRIMEA = null;
fetch('data/crimea_outline.geojson').then(r => r.json()).then(fc => { CRIMEA = fc.features[0].geometry.coordinates[0]; }).catch(() => {});
function inCrimea(lon, lat) {
  if (!CRIMEA || lon < 32.4 || lon > 36.7 || lat < 44.3 || lat > 46.3) return false;
  let inside = false;
  for (let i = 0, j = CRIMEA.length - 1; i < CRIMEA.length; j = i++) {
    const xi = CRIMEA[i][0], yi = CRIMEA[i][1], xj = CRIMEA[j][0], yj = CRIMEA[j][1];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
const UK_LAT = {'а':'a','б':'b','в':'v','г':'h','ґ':'g','д':'d','е':'e','ж':'zh','з':'z','и':'y','і':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ь':'',"'":'','ʼ':'','’':''};
const UK_LAT_START = {'є':'ye','ї':'yi','й':'y','ю':'yu','я':'ya'}, UK_LAT_MID = {'є':'ie','ї':'i','й':'i','ю':'iu','я':'ia'};
function translitUk(str) {
  let out = '', start = true;
  for (let i = 0; i < str.length; i++) {
    const ch = str[i], lo = ch.toLowerCase(), up = ch !== lo;
    let t;
    if (lo === 'з' && str[i + 1] && str[i + 1].toLowerCase() === 'г') { t = 'zgh'; i++; }
    else if (lo in UK_LAT_START) t = (start ? UK_LAT_START : UK_LAT_MID)[lo];
    else if (lo in UK_LAT) t = UK_LAT[lo];
    else { out += ch; start = !/[a-zA-Zа-яіїєґА-ЯІЇЄҐ0-9]/.test(ch); continue; }
    out += up ? t.charAt(0).toUpperCase() + t.slice(1) : t;
    start = false;
  }
  return out;
}
// Формат MVT с подменой имён у объектов внутри Крыма
class MVTUk extends ol.MVT {
  readFeatures(source, options) {
    const feats = super.readFeatures(source, options);
    if (!CRIMEA) return feats;
    for (const f of feats) {
      const p = f.getProperties ? f.getProperties() : null;
      if (!p || !p['name:uk'] || p['name:uk'] === p.name) continue;
      if (RU_CLAIM_NAMES.includes(p.name)) continue;   // российская единица: имя не менять, её снимет фильтр
      const fc = f.getFlatCoordinates ? f.getFlatCoordinates() : null;
      if (!fc || fc.length < 2) continue;
      const lon = fc[0] / R * 180 / Math.PI + LON0, lat = (2 * Math.atan(Math.exp(fc[1] / R)) - Math.PI / 2) * 180 / Math.PI;
      if (!inCrimea(lon, lat)) continue;
      p.name = p['name:uk']; p['name:nonlatin'] = p['name:uk']; p['name:latin'] = translitUk(p['name:uk']);
      if (p.name_en) p.name_en = p['name:latin']; if (p['name:en']) p['name:en'] = p['name:latin'];
    }
    return feats;
  }
}

// ---- Map ----------------------------------------------------------------------
class Map {
  constructor(opt) {
    this._h = {};                              // обработчики событий
    this._sources = {}; this._layers = {}; this._layerList = [];
    this._styleLoaded = false; this._attribText = '';
    const c = opt.center || [0, 0];
    this.view = new ol.View({projection: EE, center: fwd(c), zoom: zOL(opt.zoom || 1, c[1]),
      minZoom: 1.2, maxZoom: 16, constrainOnlyCenter: true});
    const PR = new URLSearchParams(location.search).get('pr');   // ?pr=1 - опыт: рисовать в 1 px на Retina
    this.ol = new ol.Map({target: opt.container, view: this.view, pixelRatio: PR ? +PR : undefined,
      controls: ol.control.defaults({attribution: false, zoom: false}),
      interactions: ol.interaction.defaults({altShiftDragRotate: false, pinchRotate: false})});
    this._container = typeof opt.container === 'string' ? document.getElementById(opt.container) : opt.container;
    // атрибуция: свой блок с теми же классами, что у MapLibre - index.html
    // переносит его в панель по классу .maplibregl-ctrl-attrib
    this._attrib = document.createElement('div');
    this._attrib.className = 'maplibregl-ctrl maplibregl-ctrl-attrib';
    this._attrib.style.cssText = 'position:absolute;right:0;bottom:0;font:11px/1.3 system-ui,sans-serif;background:rgba(20,23,28,.7);padding:2px 6px;z-index:3;';
    this._container.appendChild(this._attrib);
    // на телефоне index.html вешает класс maplibregl-compact: сворачиваем в кнопку ⓘ
    this._attrib.addEventListener('click', e => {
      if (!this._attrib.classList.contains('maplibregl-compact')) return;
      if (e.target.closest('a')) return;
      this._attrib.classList.toggle('open'); this._renderAttrib();
    });
    if (!document.getElementById('ee-attrib-css')) {
      const st = document.createElement('style'); st.id = 'ee-attrib-css';
      st.textContent = '.maplibregl-ctrl-attrib.maplibregl-compact:not(.open){width:22px;height:22px;padding:0;border-radius:11px;overflow:hidden;text-align:center;line-height:22px;cursor:pointer;margin:0 8px 8px 0}'
        + '.maplibregl-ctrl-attrib.maplibregl-compact:not(.open) .txt{display:none}'
        + '.maplibregl-ctrl-attrib.maplibregl-compact:not(.open):before{content:"ⓘ";color:#9aa4ad}'
        + '.maplibregl-ctrl-attrib.maplibregl-compact.open{max-width:calc(100vw - 16px);cursor:pointer}';
      document.head.appendChild(st);
    }
    this._styleUrl = opt.style;
    // шрифт подписей всегда из репозитория: явная ссылка, не полагаясь на
    // определение olms (на машине со своим Noto Sans он ничего не грузит)
    if (!document.getElementById('ee-font-css')) {
      for (const w of ['400', '300']) {
        const l = document.createElement('link'); l.id = w === '400' ? 'ee-font-css' : 'ee-font-css-300'; l.rel = 'stylesheet'; l.href = `vendor/fonts/noto-sans/${w}.css`;
        document.head.appendChild(l);
      }
    }
    this._basemap().catch(e => this._emit('error', {error: e}));
    // события камеры
    this.ol.on('movestart', () => this._emit('movestart', {}));
    this.ol.on('rendercomplete', () => this._emit('idle', {}));   // MapLibre: 'idle' - кадр дорисован
    this.ol.on('moveend', () => { this._emit('moveend', {}); this._emit('zoomend', {}); });
    this.view.on('change:center', () => this._emit('move', {}));
    this.view.on('change:resolution', () => this._emit('move', {}));
    this.ol.on('pointerdrag', () => this._emit('dragstart', {originalEvent: true}));
    this.ol.getViewport().addEventListener('wheel', () => this._emit('zoomstart', {originalEvent: true}), {passive: true});
    this.ol.on('singleclick', e => {
      const ll = ol.proj.toLonLat(e.coordinate, EE);
      this._emit('click', {lngLat: {lng: ll[0], lat: ll[1]}, point: e.pixel, originalEvent: e.originalEvent});
    });
  }
  async _basemap() {
    // Опыт 05.09 (?base=esri): растровая подложка Esri Dark Gray (та же, что в
    // Leaflet-режиме старой карты) + отдельный растровый слой подписей;
    // OpenLayers перепроецирует растр триангуляцией без пересчёта вершин.
    if (new URLSearchParams(location.search).get('base') === 'esri') {
      const mk = (name, z) => new ol.TileLayer({zIndex: z, source: new ol.XYZ({
        url: `https://server.arcgisonline.com/ArcGis/rest/services/Canvas/${name}/MapServer/tile/{z}/{y}/{x}`,
        maxZoom: 16, crossOrigin: 'anonymous', attributions: 'Подложка: Esri, HERE, Garmin, OpenStreetMap contributors'})});
      const base = mk('World_Dark_Gray_Base', 10), ref = mk('World_Dark_Gray_Reference', 200);
      const Q = new URLSearchParams(location.search); if (Q.get('lblo')) ref.setOpacity(+Q.get('lblo'));
      this.ol.addLayer(base); this.ol.addLayer(ref);
      this._baseAttrib = 'Подложка: Esri'; this._renderAttrib(); this._styleLoaded = true;
      this._emit('load', {}); this._emit('styledata', {}); this._emit('sourcedata', {});
      return;
    }
    const style = await (await fetch(this._styleUrl)).json();
    if (!CRIMEA) { try { CRIMEA = (await (await fetch('data/crimea_outline.geojson')).json()).features[0].geometry.coordinates[0]; } catch (e) {} }
    const srcDef = style.sources && style.sources.openmaptiles;
    if (!srcDef) {                          // заглушка стиля (офлайн-кадры): только фон, без тайлов
      olms.applyBackground(this.ol, style);
      this._baseAttrib = ''; this._renderAttrib(); this._styleLoaded = true;
      this._emit('load', {}); this._emit('styledata', {}); this._emit('sourcedata', {});
      return;
    }
    const tj = srcDef.url ? await (await fetch(srcDef.url)).json() : srcDef;
    const tpl = tj.tiles[0];
    // тайл x нашей сетки = тайл OSM (x + 2^z/4) mod 2^z - целое при z >= 2
    const urlFn = tc => { const z = tc[0], n = 1 << z; return tpl.replace('{z}', z).replace('{x}', (tc[1] + n / 4) % n).replace('{y}', tc[2]); };
    const grid = ol.tilegrid.createXYZ({minZoom: 2, maxZoom: tj.maxzoom || 14, tileSize: 512});
    const source = new ol.VectorTileSource({format: new MVTUk(), projection: M, tileGrid: grid, tileUrlFunction: urlFn});
    // Подписи и заливки берут ОДИН источник: два источника на одних адресах
    // разбирали каждый тайл дважды. Тайлы на зум мельче теперь только до зума 5,
    // где подписей мало (страны, области); на 5,8 с/кадр в виде на Украину
    // (замер 05.09) приходилось при +1 на всех зумах.
    // Границы, которые «хочет видеть» только Россия (claimed_by=RU: линия по
    // Перекопу, Абхазия, Южная Осетия), из подложки убираются - остаются
    // признанные границы. Резолюция ГА ООН 68/262 - в наших же данных.
    for (const l of style.layers)
      if (l['source-layer'] === 'boundary' && l.type === 'line') {
        const claim = ['!=', ['coalesce', ['get', 'claimed_by'], ''], 'RU'];
        l.filter = l.filter ? ['all', l.filter, claim] : claim;
      }
    // Подписи российских единиц на чужой земле: в OSM рядом с «Автономна
    // Республіка Крим» лежит отдельная точка «Республика Крым» (place=state).
    // Снимаем по имени; список - по тайлам z6 вокруг Чёрного моря и Кавказа
    // 05.09.2026 (других таких точек в place нет: ДНР/ЛНР, Абхазия, Южная
    // Осетия в слое place не значатся).
    // Переименования подписей подложки (куратор 05.09): ключ - name в OSM,
    // значение - строки латиницей и кириллицей, как их рисует стиль.
    const RENAMES = {
      'Чечня': ['Chechen Republic of Ichkeria', 'Чеченская Республика Ичкерия'],
    };
    for (const l of style.layers)
      if (l['source-layer'] === 'place' && l.type === 'symbol') {
        const notClaim = ['all', ['!', ['in', ['coalesce', ['get', 'name'], ''], ['literal', RU_CLAIM_NAMES]]],
                                 ['!', ['in', ['coalesce', ['get', 'name:en'], ''], ['literal', RU_CLAIM_NAMES]]]];
        l.filter = l.filter ? ['all', l.filter, notClaim] : notClaim;
        if (l.layout && l.layout['text-field']) {
          const cases = ['case'];
          for (const [k, v] of Object.entries(RENAMES)) cases.push(['==', ['coalesce', ['get', 'name'], ''], k], v[0] + '\n' + v[1]);
          cases.push(l.layout['text-field']);
          l.layout['text-field'] = cases;
        }
      }
    // Зум для стиля - меркаторский (тайлы 512, широта центра карты 55°):
    // иначе стиль считает зум Equal Earth на ~1,6 больше и включает подписи и
    // границы z5+ уже на обзоре.
    const RES = []; for (let z = 0; z <= 24; z++) RES.push(78271.517 * Math.cos(55 * Math.PI / 180) / Math.pow(2, z));
    // Опыты с подписями (обсуждение 05.09): ?lblw=300 - тоньше шрифт (Noto Sans Light),
    // ?lbld=-1 - подписи на 1 px мельче, ?lblo=0.6 - прозрачность слоя подписей.
    const Q = new URLSearchParams(location.search);
    // Куратор 05.09: буквы у OpenLayers жирнее и ярче, чем у MapLibre (SDF на GPU);
    // ближе всего по весу - Noto Sans Light (vendor/fonts/noto-sans/300.css),
    // а строку названия ломать не раньше 14 em (у MapLibre перенос мягкий, и
    // «VINNYTSYA OBLAST» стоит одной строкой). ?lblw=400 - обычный, ?lblmw=N - ширина.
    const LBLW = Q.get('lblw') || '300', LBLD = +(Q.get('lbld') || 0), LBLMW = +(Q.get('lblmw') || 14);
    for (const l of style.layers) {
      if (l.type !== 'symbol' || !l.layout) continue;
      if (l.layout['text-font']) l.layout['text-font'] = l.layout['text-font'].map(f => f.replace(/ Regular$/, LBLW === '300' ? ' Light' : (LBLW === '500' ? ' Medium' : ' Regular')));
      if (l.layout['text-field'] && l.layout['text-max-width'] === undefined) l.layout['text-max-width'] = LBLMW;
      if (LBLD && l.layout['text-size'] !== undefined) {
        const ts = l.layout['text-size'];
        l.layout['text-size'] = typeof ts === 'number' ? Math.max(6, ts + LBLD) : ['+', ts, LBLD];
      }
    }
    const ids = style.layers.filter(l => l.source === 'openmaptiles').map(l => l.id);
    const symbol = new Set(style.layers.filter(l => l.type === 'symbol').map(l => l.id));
    // стиль двумя слоями: заливки/линии (10) и подписи (20) - ОБА под нашим
    // красным (100+), как у старой карты на MapLibre: подпись в красной зоне
    // приглушена заливкой. (В прототипе подписи стояли над красным, как в
    // телефонном Leaflet-режиме; куратор 05.09: «текст ПОД красным».)
    const below = new ol.VectorTileLayer({source, declutter: false, zIndex: 10});
    const labels = new ol.VectorTileLayer({source, declutter: true, zIndex: 20});
    // Шрифт подписей из репозитория (vendor/fonts/noto-sans, OFL), а не с jsdelivr
    const FONTS = 'vendor/fonts/{font-family}/{fontweight}{-fontstyle}.css';
    await olms.applyStyle(below, style, ids.filter(i => !symbol.has(i)), {styleUrl: this._styleUrl, webfonts: FONTS}, RES);
    await olms.applyStyle(labels, style, ids.filter(i => symbol.has(i)), {styleUrl: this._styleUrl, webfonts: FONTS}, RES);
    source.setTileUrlFunction(urlFn);        // applyStyle подменяет адреса тайлов
    below.setMaxResolution(Infinity); labels.setMaxResolution(Infinity);   // и режет малые зумы
    olms.applyBackground(this.ol, style);
    // «го» куратора 05.09: подписи приглушены до 0,65 - по яркости ближе всего к
    // старой карте (MapLibre рисует глифы по полю расстояний, штрих тоньше и цвет
    // не доходит до заданного); ?lblo=1 - без приглушения.
    labels.setOpacity(Q.get('lblo') ? +Q.get('lblo') : 0.65);
    // Заливки и линии подложки рисуются в 1 px даже на Retina (?fillpr=2 -
    // выключить): вчетверо меньше растровой работы при зуме, а подписи и
    // красное остаются в полном разрешении.
    const FILLPR = +(Q.get('fillpr') || 1);
    if (FILLPR !== 2) {
      const r = below.getRenderer(); const origRF = r.renderFrame;
      r.renderFrame = function (frameState, target) { return origRF.call(this, Object.assign({}, frameState, {pixelRatio: FILLPR}), target); };
    }
    this.ol.addLayer(below); this.ol.addLayer(labels);
    this._baseAttrib = tj.attribution || '';
    this._renderAttrib();
    this._styleLoaded = true;
    this._emit('load', {}); this._emit('styledata', {}); this._emit('sourcedata', {});
  }
  _renderAttrib() {
    const parts = [this._baseAttrib];
    for (const id in this._sources) if (this._sources[id].attribution) parts.push(this._sources[id].attribution);
    this._attrib.innerHTML = '<span class="txt">' + parts.filter(Boolean).join(' · ') + '</span>';
  }
  // ---- события
  on(ev, fn) { (this._h[ev] = this._h[ev] || []).push(fn); return this; }
  once(ev, fn) { const w = e => { this.off(ev, w); fn(e); }; return this.on(ev, w); }
  off(ev, fn) { if (this._h[ev]) this._h[ev] = this._h[ev].filter(f => f !== fn); return this; }
  _emit(ev, e) { for (const f of (this._h[ev] || []).slice()) { try { f(e); } catch (x) { console.error(x); } } }
  // ---- состояние
  isStyleLoaded() { return this._styleLoaded; }
  isMoving() { return this.view.getAnimating() || this.view.getInteracting(); }
  loaded() { return this._styleLoaded; }
  getContainer() { return this._container; }
  getCanvas() { return this.ol.getViewport(); }
  addControl(ctl) { if (ctl && ctl._ol) this.ol.addControl(ctl._ol); return this; }
  resize() { this.ol.updateSize(); return this; }
  triggerRepaint() { this.ol.render(); return this; }
  // ---- камера
  getCenter() { const ll = ol.proj.toLonLat(this.view.getCenter(), EE); return {lng: ll[0], lat: ll[1]}; }
  getZoom() { return zML(this.view.getZoom(), this.getCenter().lat); }
  getMinZoom() { return zML(this.view.getMinZoom(), this.getCenter().lat); }
  setMinZoom(z) { this.view.setMinZoom(Math.max(1.2, zOL(z, this.getCenter().lat))); return this; }
  setCenter(c) { this.view.setCenter(fwd(c)); return this; }
  setZoom(z) { this.view.setZoom(zOL(z, this.getCenter().lat)); return this; }
  jumpTo(o) {
    if (o.center) this.view.setCenter(fwd(o.center));
    if (o.zoom !== undefined) this.view.setZoom(zOL(o.zoom, (o.center || [0, this.getCenter().lat])[1]));
    return this;
  }
  easeTo(o) {
    const lat = (o.center || [0, this.getCenter().lat])[1];
    const a = {duration: o.duration === undefined ? 300 : o.duration};
    if (o.center) a.center = fwd(o.center);
    if (o.zoom !== undefined) a.zoom = zOL(o.zoom, lat);
    this.view.animate(a); return this;
  }
  fitBounds(b, o) {
    const p = (o && o.padding) || 0;
    const ext = ol.proj.transformExtent([b[0][0], b[0][1], b[1][0], b[1][1]], 'EPSG:4326', EE);
    this.view.fit(ext, {padding: [p, p, p, p], duration: (o && o.duration) || 0});
    return this;
  }
  getBounds() {
    const e = ol.proj.transformExtent(this.view.calculateExtent(this.ol.getSize() || [1, 1]), EE, 'EPSG:4326');
    return {getWest: () => e[0], getSouth: () => e[1], getEast: () => e[2], getNorth: () => e[3]};
  }
  // ---- источники
  addSource(id, def) {
    if (this._sources[id]) throw new Error('source exists: ' + id);
    const self = this;
    if (def.type === 'geojson') {
      const src = new ol.VectorSource();
      const rec = {kind: 'geojson', src, _attr: '', _data: {type: 'FeatureCollection', features: []},
        setData(fc) { this._data = fc || {type: 'FeatureCollection', features: []}; src.clear(true); if (fc && fc.features && fc.features.length) src.addFeatures(FMT.readFeatures(fc)); },
        get attribution() { return this._attr; },
        set attribution(v) { this._attr = v; self._renderAttrib(); }};
      this._sources[id] = rec;
      if (def.data && def.data.features && def.data.features.length) rec.setData(def.data);
    } else if (def.type === 'raster') {
      const src = new ol.XYZ({url: def.tiles[0], tileSize: def.tileSize || 256, maxZoom: def.maxzoom || 18,
        attributions: def.attribution, crossOrigin: 'anonymous'});
      this._sources[id] = {kind: 'raster', src, attribution: def.attribution || ''};
      this._renderAttrib();
    } else throw new Error('source type: ' + def.type);
    return this;
  }
  removeSource(id) { delete this._sources[id]; return this; }
  getSource(id) { return this._sources[id]; }
  // ---- слои
  addLayer(def) {
    const s = this._sources[def.source];
    if (!s) throw new Error('no source ' + def.source);
    const paint = def.paint || {}, layout = def.layout || {};
    const z = 100 + this._layerList.length;   // порядок добавления = порядок сверху; подписи подложки на 200
    let layer;
    if (def.type === 'raster') {
      layer = new ol.TileLayer({source: s.src, zIndex: 50, opacity: paint['raster-opacity'] === undefined ? 1 : paint['raster-opacity']});
    } else {
      const rec = {paint: {...paint}, filter: def.filter, type: def.type, style: null};
      const build = () => {
        const pt = rec.paint;
        if (def.type === 'fill')
          rec.style = new ol.Style({fill: new ol.Fill({color: hex(pt['fill-color'] || '#000', pt['fill-opacity'] === undefined ? 1 : pt['fill-opacity'])})});
        else
          rec.style = new ol.Style({stroke: new ol.Stroke({color: hex(pt['line-color'] || '#000', pt['line-opacity'] === undefined ? 1 : pt['line-opacity']),
            width: pt['line-width'] || 1, lineDash: pt['line-dasharray'] ? pt['line-dasharray'].map(v => v * (pt['line-width'] || 1)) : undefined})});
      };
      build();
      layer = new ol.VectorLayer({source: s.src, zIndex: z, style: f => matches(rec.filter, f) ? rec.style : null});
      layer._rec = rec; layer._rebuild = build;
    }
    if (layout.visibility === 'none') layer.setVisible(false);
    this._layers[def.id] = layer; this._layerList.push(def.id);
    this.ol.addLayer(layer);
    return this;
  }
  getLayer(id) { return this._layers[id]; }
  setLayoutProperty(id, prop, v) { const l = this._layers[id]; if (l && prop === 'visibility') l.setVisible(v !== 'none'); return this; }
  setPaintProperty(id, prop, v) {
    const l = this._layers[id]; if (!l) return this;
    if (prop === 'raster-opacity') { l.setOpacity(v); return this; }
    if (l._rec) { l._rec.paint[prop] = v; l._rebuild(); l.changed(); }
    return this;
  }
  getPaintProperty(id, prop) { const l = this._layers[id]; return l && l._rec ? l._rec.paint[prop] : undefined; }
  setFilter(id, f) { const l = this._layers[id]; if (l && l._rec) { l._rec.filter = f; l.changed(); } return this; }
}

// ---- Popup: тот же интерфейс, что у maplibregl.Popup, поверх ol.Overlay -------
class Popup {
  constructor(opt) {
    this._opt = opt || {};
    const el = document.createElement('div');
    el.className = 'maplibregl-popup maplibregl-popup-anchor-bottom ' + (this._opt.className || '');
    // контейнер оверлея OpenLayers нулевой ширины: без width:max-content попап
    // сжимается в столбик по слову
    el.style.width = 'max-content';
    el.innerHTML = '<div class="maplibregl-popup-tip"></div><div class="maplibregl-popup-content"></div>';
    // (у MapLibre max-width контейнера перебивает правило .hist !important -
    // попап истории растягивался на 1380 px; здесь предел ставим содержимому)
    el.querySelector('.maplibregl-popup-content').style.maxWidth = this._opt.maxWidth || '240px';
    const btn = document.createElement('button');
    btn.className = 'maplibregl-popup-close-button'; btn.type = 'button'; btn.textContent = '×'; btn.title = 'закрыть';
    btn.onclick = () => this.remove();
    el.querySelector('.maplibregl-popup-content').appendChild(btn);
    this._el = el; this._html = ''; this._map = null;
    this._ov = new ol.Overlay({element: el, positioning: 'bottom-center', offset: [0, -6], stopEvent: true, insertFirst: false});
  }
  setLngLat(ll) { this._ll = ll; this._ov.setPosition(fwd([ll.lng, ll.lat])); return this; }
  setHTML(h) {
    const c = this._el.querySelector('.maplibregl-popup-content');
    const btn = c.querySelector('.maplibregl-popup-close-button');
    c.innerHTML = h; c.appendChild(btn);
    return this;
  }
  addTo(map) { this._map = map; map.ol.addOverlay(this._ov); return this; }
  remove() { if (this._map) { this._map.ol.removeOverlay(this._ov); this._map = null; } return this; }
  isOpen() { return !!this._map; }
  getElement() { return this._el; }
}
class NavigationControl { constructor() { this._ol = new ol.control.Zoom(); } }

window.maplibregl = {Map, Popup, NavigationControl, EE, zOL, zML};
})();
