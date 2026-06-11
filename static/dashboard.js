// MOCHA — Phase 1 KPI dashboard (galaxy/mars/adult) + view routing

const DASH = {
  domains: {},        // {galaxy: {label, range:{min,max}}, ...}
  charts: {},         // {[domain]: {ts: Chart, actions: Chart}}
  initialized: {},    // {[domain]: true}
  lastData: {},       // {[domain]: 마지막 summary 응답 — 테마 토글 시 refetch 없이 재렌더}
  seriesCache: {},    // {[domain]: {key, dates, series, fmts}}
  activeQuery: {},    // {[domain]: latest queryKey, to drop stale responses}
  modalChart: null,
  modalCtx: null,
};

const fmt = {
  num(n) {
    if (n == null || isNaN(n)) return "—";
    if (n >= 100_000_000) return (n / 100_000_000).toFixed(1) + "억";
    if (n >= 10_000) return (n / 10_000).toFixed(1) + "만";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "천";
    return n.toLocaleString();
  },
  numFull(n) { return n == null ? "—" : Number(n).toLocaleString(); },
  card(value, kind) {
    if (value == null || isNaN(value)) return "—";
    if (kind === "int") return fmt.num(value);
    if (kind === "f2")  return Number(value).toFixed(2);
    if (kind === "pct") return (Number(value) * 100).toFixed(2) + "%";
    return String(value);
  },
  cardMeta(value, kind) {
    if (kind === "int" && value >= 1000) return Number(value).toLocaleString();
    if (kind === "pct") return Number(value).toFixed(4);
    return "";
  },
};

// Read CSS var values so charts pick up the active theme
function themeColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
function applyChartTheme() {
  Chart.defaults.color = themeColor("--ink-soft", "#9ba1b3");
  Chart.defaults.borderColor = themeColor("--border", "#262b38");
  Chart.defaults.font.family = '"Pretendard Variable", Pretendard, sans-serif';
}
applyChartTheme();

// Theme management
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("mocha:theme", theme); } catch {}
  applyChartTheme();
  // Chart.js 는 생성 시점에 Chart.defaults 색을 굳히므로, 새 색을 적용하려면
  // 차트를 다시 만들어야 한다. 단 full loadKpi 는 summary/series refetch + LLM
  // insight 재호출(3-8s)까지 유발 → 캐시된 data 로 렌더만 재실행한다.
  for (const dom of Object.keys(DASH.charts)) {
    if (DASH.activeQuery[dom] && DASH.lastData[dom]) {
      renderKpi(dom, DASH.lastData[dom]);
      paintSparklines(dom);  // seriesCache 로 sparkline 도 새 색으로 다시 그림
    }
  }
  // Force-redraw modal chart if open
  const modal = document.getElementById("kpi-modal");
  if (modal && !modal.hidden && DASH.modalChart) {
    DASH.modalChart.update();
  }
}
function initTheme() {
  let t = "dark";
  try {
    const saved = localStorage.getItem("mocha:theme");
    if (saved === "light" || saved === "dark") t = saved;
  } catch {}
  document.documentElement.dataset.theme = t;
  applyChartTheme();
}
initTheme();

// Chat view theme toggle — same handler, same setTheme.
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.querySelector(".chat-header .theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "dark";
      setTheme(current === "dark" ? "light" : "dark");
    });
  }
});

// ───────── view router ─────────
function showView(name) {
  for (const el of document.querySelectorAll(".view")) el.hidden = el.dataset.view !== name;
  for (const b of document.querySelectorAll(".rail-item")) {
    b.classList.toggle("active", b.dataset.view === name);
  }
  try { localStorage.setItem("mocha:view", name); } catch {}
  if (["galaxy", "mars", "adult"].includes(name)) ensureKpiInit(name);
}

document.querySelectorAll(".rail-item").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view))
);

// ───────── KPI init / render ─────────
async function fetchDomainsMeta() {
  const r = await fetch("/api/kpi/domains");
  const data = await r.json();
  for (const d of data.domains) {
    DASH.domains[d.key] = { label: d.label, range: data.ranges[d.key] };
  }
}

function mountKpiView(domain) {
  const container = document.getElementById("view-" + domain);
  if (container.dataset.mounted) return;
  const tpl = document.getElementById("kpi-template");
  const node = tpl.content.firstElementChild.cloneNode(true);
  container.appendChild(node);
  container.dataset.mounted = "1";

  const meta = DASH.domains[domain] || { label: domain.toUpperCase(), range: {} };
  node.querySelector(".kpi-title").textContent = meta.label;

  const startInp = node.querySelector(".kpi-start");
  const endInp = node.querySelector(".kpi-end");
  const max = meta.range.max || new Date().toISOString().slice(0, 10);
  const maxDate = new Date(max);
  const defaultStart = new Date(maxDate);
  defaultStart.setDate(defaultStart.getDate() - 6);
  endInp.value = max;
  startInp.value = defaultStart.toISOString().slice(0, 10);
  if (meta.range.min) { startInp.min = meta.range.min; endInp.min = meta.range.min; }
  startInp.max = max; endInp.max = max;

  node.querySelector(".kpi-refresh").addEventListener("click", () => {
    // 명시적 새로고침 — AdultPlus cache 우회 (force=true 전달용 표시)
    const root = container.querySelector(".kpi-view");
    if (root) root.dataset.kpiForceRefresh = "1";
    loadKpi(domain);
  });
  startInp.addEventListener("change", () => loadKpi(domain));
  endInp.addEventListener("change", () => loadKpi(domain));

  // Theme toggle — moved to global floating button in rail. In-view toggle removed.
  const localToggle = node.querySelector(".theme-toggle");
  if (localToggle) {
    localToggle.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "dark";
      setTheme(current === "dark" ? "light" : "dark");
    });
  }

  // AI insight refresh (now inside main panel above timeseries)
  node.querySelector(".aside-insight-refresh").addEventListener("click", () => {
    loadInsights(domain, /*force=*/true);
  });

  // Expand all-KPI modal
  node.querySelector(".kpi-expand-btn").addEventListener("click", () => openAllKpiModal(domain));

  // KPI 카드 / metric 행 클릭 → 모달. 이벤트 위임으로 mount 시 1회만 바인딩
  // (이전엔 renderKpi 마다 모든 카드/행에 addEventListener 재부착 — 테마 토글/새로고침
  //  시 반복 비용). 컨테이너는 재렌더해도 유지되고 innerHTML 만 바뀐다.
  const cardsWrap = node.querySelector(".kpi-cards");
  if (cardsWrap) cardsWrap.addEventListener("click", (e) => {
    const card = e.target.closest(".kpi-card[data-label]");
    if (card) openKpiModal(domain, card.dataset.label, card.dataset.kind);
  });
  const metricTable = node.querySelector(".kpi-metric-table");
  if (metricTable) metricTable.addEventListener("click", (e) => {
    const tr = e.target.closest("tbody tr[data-label]");
    if (tr) openKpiModal(domain, tr.dataset.label, tr.dataset.kind);
  });

  // TOP panel tab switcher (콘텐츠 / 장르)
  node.querySelectorAll(".tab-switcher .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const wrap = tab.closest(".kpi-panel");
      wrap.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const which = tab.dataset.tab;
      wrap.querySelector(".top10-contents").hidden = which !== "contents";
      wrap.querySelector(".top10-genres").hidden = which !== "genres";
    });
  });

  // galaxy/mars/adult 도메인 — 기존 표준 패널 모두 숨김.
  // AI 인사이트 + range picker + 도메인별 커스텀 dashboard 만 노출.
  // .kpi-aside 는 유지 (오른쪽 필터 sidebar 로 재사용).
  if (domain === "adult" || domain === "mars" || domain === "galaxy") {
    container.classList.add("custom-dashboard-only");
    node.querySelectorAll(
      ".kpi-basis-note, .kpi-cards-hero, .kpi-panel-chart, " +
      ".kpi-row, .kpi-panel-revenue, .kpi-row-4col, " +
      ".kpi-panel-donut, .kpi-foot"
    ).forEach((el) => { el.style.display = "none"; });
    // aside 안의 기존 panel 들 (summary / content_type filter / action filter)
    // 도 hide — AdultPlus 필터로 교체.
    node.querySelectorAll(".kpi-aside .aside-panel").forEach((el) => {
      el.style.display = "none";
    });
    mountAdultplusFilters(node.querySelector(".kpi-aside"), domain);
  }

  // adult 도메인 — AdultPlus funnel (mars 추천 슬롯의 성인+) 마운트.
  if (domain === "adult") {
    mountMarsAdultplus(container);
  }
  // mars 도메인 — SVOD/TVOD 탭 UI 마운트.
  if (domain === "mars") {
    mountMarsTabs(container);
  }
  // galaxy 도메인 — archive 기반 funnel dashboard (AdultPlus 와 동일 양식)
  if (domain === "galaxy") {
    mountGalaxyFunnel(container);
  }
}

// ── AdultPlus filters sidebar (PDF Datastudio 와 동일 4축) ──────────────
// adult/mars 공용. 변경 시 dashboard refetch.

const AP_FILTER_DEFS = [
  {
    key: "age_group", label: "Age groups",
    options: [
      { v: "18_24", label: "18-24" },
      { v: "25_34", label: "25-34" },
      { v: "35_44", label: "35-44" },
      { v: "45_plus", label: "45+" },
    ],
  },
  {
    key: "client", label: "Clients",
    options: [
      { v: "1", label: "iOS" },
      { v: "2", label: "Android" },
      { v: "3", label: "Web" },
    ],
  },
  {
    key: "subscribe", label: "Subscribes",
    options: [
      { v: "subscribed", label: "Subscribed" },
      { v: "non_subscribe", label: "Non-Subscribe" },
      { v: "newbie", label: "Newbie" },
    ],
  },
  {
    key: "country", label: "Countries",
    options: [
      { v: "KR", label: "한국" },
      { v: "JP", label: "일본" },
    ],
  },
];

function mountAdultplusFilters(asideEl, domain) {
  if (!asideEl || asideEl.querySelector(".ap-filters")) return;
  const wrap = document.createElement("div");
  wrap.className = "ap-filters";
  // default = 모두 체크 (사용자 직관: "전부 보고 있다")
  wrap.innerHTML = `
    <div class="ap-filter-head">
      <h4>필터</h4>
      <button class="ap-filter-reset" type="button" title="모두 선택">전체</button>
    </div>
    ${AP_FILTER_DEFS.map((f) => `
      <div class="ap-filter-group" data-key="${escapeHtmlD(f.key)}">
        <div class="ap-filter-label">${escapeHtmlD(f.label)}</div>
        <ul class="ap-filter-list">
          ${f.options.map((o) => `
            <li>
              <label>
                <input type="checkbox" value="${escapeHtmlD(o.v)}" checked>
                ${escapeHtmlD(o.label)}
              </label>
            </li>`).join("")}
        </ul>
      </div>
    `).join("")}
  `;
  asideEl.appendChild(wrap);

  // Filter changes → debounced refetch
  const refetch = () => {
    if (domain === "adult") {
      const root = document.querySelector("#view-adult .kpi-view");
      if (root) loadMarsAdultplus(root.querySelector(".kpi-start"),
                                  root.querySelector(".kpi-end"));
    } else if (domain === "mars") {
      const root = document.querySelector("#view-mars .kpi-view");
      if (root) loadMarsTabActive(root);
    }
  };
  let timer = 0;
  const debounced = () => { clearTimeout(timer); timer = setTimeout(refetch, 350); };
  wrap.addEventListener("change", debounced);
  // "전체" 버튼 — 모두 체크 (default 복원)
  wrap.querySelector(".ap-filter-reset").addEventListener("click", () => {
    wrap.querySelectorAll("input[type=checkbox]").forEach((c) => { c.checked = true; });
    refetch();
  });
}

function collectAdultplusFilters(domain) {
  const view = document.getElementById("view-" + domain);
  const wrap = view?.querySelector(".ap-filters");
  if (!wrap) return {};
  const out = {};
  // 전체 선택 시 = 필터 없음 (URL param 생략 → BQ WHERE 안 붙음 → cache key 안정)
  // 일부만 선택 시만 그 값들을 CSV 로 전달
  wrap.querySelectorAll(".ap-filter-group").forEach((g) => {
    const all = Array.from(g.querySelectorAll("input[type=checkbox]"));
    const checked = all.filter((c) => c.checked).map((c) => c.value);
    if (checked.length > 0 && checked.length < all.length) {
      out[g.dataset.key] = checked.join(",");
    }
    // 0개 체크 또는 전체 체크 → 필터 미지정 (= 전체 데이터)
  });
  return out;
}

// ── Mars × SVOD/TVOD tabs — 두 탭 모두 AdultPlus 와 동일 양식 (PDF style) ──
function mountMarsTabs(container) {
  if (container.querySelector(".mars-tabs")) return;
  const sec = document.createElement("section");
  sec.className = "mars-tabs";
  sec.innerHTML = `
    <div class="mars-tab-switcher" role="tablist">
      <button class="mars-tab active" data-tab="svod">📺 SVOD (구독제)</button>
      <button class="mars-tab" data-tab="tvod">💳 TVOD (결제)</button>
    </div>
    <div class="mars-tab-panes">
      <div class="mars-tab-pane" data-pane="svod"></div>
      <div class="mars-tab-pane" data-pane="tvod" hidden></div>
    </div>
  `;
  // .kpi-main 안에 mount — AI 인사이트와 동일 width
  const target = container.querySelector(".kpi-main") || container;
  target.appendChild(sec);

  // 각 탭 pane 안에 AdultPlus 와 동일한 dashboard 마운트
  mountMarsDashboardIn(sec.querySelector("[data-pane='svod']"), "svod");
  mountMarsDashboardIn(sec.querySelector("[data-pane='tvod']"), "tvod");

  // 탭 스위처
  sec.querySelectorAll(".mars-tab").forEach((t) => {
    t.addEventListener("click", () => {
      sec.querySelectorAll(".mars-tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      const which = t.dataset.tab;
      sec.querySelectorAll(".mars-tab-pane").forEach((p) => {
        p.hidden = p.dataset.pane !== which;
      });
      const root = container.querySelector(".kpi-view");
      if (root) loadMarsTabActive(root);
    });
  });
}

function mountMarsDashboardIn(pane, kind) {
  // AdultPlus 의 mountMarsAdultplus 와 동일한 dashboard 마크업을 그대로 재사용.
  // 클래스명은 .mars-adultplus 그대로 (CSS 재사용). 단 data-kind 로 svod/tvod 구분.
  if (pane.querySelector(".mars-adultplus")) return;
  // tempContainer 트릭: mountMarsAdultplus 가 .kpi-main 또는 container 에 append
  // 하므로, pane 을 직접 target 으로 쓰려면 임시 wrapper 가 필요. 그냥 인라인.
  const sec = document.createElement("section");
  sec.className = "mars-adultplus";
  sec.dataset.kind = kind;
  const kindLabel = kind === "svod" ? "SVOD (구독제)" : "TVOD (결제)";
  const tableName = kind === "svod" ? "remy_mars_kpi_stats" : "remy_mars_kpi_tod_stats";
  sec.innerHTML = `
    <header class="ap-header">
      <div>
        <h2 class="ap-title">${kind === "svod" ? "📺" : "💳"} Mars ${escapeHtmlD(kindLabel)} funnel</h2>
        <p class="ap-sub">mars 추천 슬롯 노출/클릭 funnel · BQ <code>${escapeHtmlD(tableName)}</code></p>
      </div>
      <span class="ap-status" aria-live="polite">대기 중</span>
    </header>
    <div class="ap-hero">
      <div class="ap-stat" data-stat="rows_click_ratio">
        <div class="ap-stat-label">Rows: click ratio</div><div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="cells_action_ratio">
        <div class="ap-stat-label">Cells: action ratio</div><div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="unique_users">
        <div class="ap-stat-label">Unique users</div><div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="total_recommends">
        <div class="ap-stat-label">Total recommends</div><div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="elapsed_median_ms">
        <div class="ap-stat-label">Elapsed: median (ms)</div><div class="ap-stat-value">—</div>
      </div>
    </div>
    <div class="ap-grid-2">
      <div class="ap-panel"><div class="ap-panel-head"><h3>Exposed · Actioned · ratio</h3><span class="ap-panel-sub">rs 기반</span></div><div class="ap-chart-wrap"><canvas class="ap-ts-actions"></canvas></div></div>
      <div class="ap-panel"><div class="ap-panel-head"><h3>Exposed · Clicked · ratio</h3><span class="ap-panel-sub">rs 기반</span></div><div class="ap-chart-wrap"><canvas class="ap-ts-clicks"></canvas></div></div>
      <div class="ap-panel"><div class="ap-panel-head"><h3>Clicked · Wished · Played · Purchased</h3><span class="ap-panel-sub">cs 기반 + ratios</span></div><div class="ap-chart-wrap"><canvas class="ap-ts-funnel"></canvas></div></div>
      <div class="ap-panel"><div class="ap-panel-head"><h3>Users · Recommends</h3><span class="ap-panel-sub">일별</span></div><div class="ap-chart-wrap"><canvas class="ap-ts-users"></canvas></div></div>
    </div>
    <div class="ap-grid-3">
      <div class="ap-panel"><div class="ap-panel-head"><h3>Rows: exposed</h3></div><div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-exposed"></canvas></div></div>
      <div class="ap-panel"><div class="ap-panel-head"><h3>Rows: clicked</h3></div><div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-clicked"></canvas></div></div>
      <div class="ap-panel"><div class="ap-panel-head"><h3>Actions</h3></div><div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-actions"></canvas></div></div>
    </div>
    <div class="ap-panel ap-rows-table-panel">
      <div class="ap-panel-head"><h3>Row × funnel</h3><span class="ap-panel-sub">rs.key 별 · 노출률 / 클릭률</span></div>
      <div class="ap-rows-table-wrap">
        <table class="ap-table ap-rows-table">
          <thead><tr><th>#</th><th>Row</th><th class="num">Served</th><th class="num">Exposed</th><th class="num">Expose ratio</th><th class="num">Clicked</th><th class="num">Click ratio</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
    <div class="ap-panel ap-table-panel">
      <div class="ap-panel-head"><h3>Title × funnel</h3><span class="ap-panel-sub">cs 기반 · TOP 50 · 10행 후 스크롤</span></div>
      <div style="overflow-x:auto;">
        <table class="ap-table ap-title-table">
          <thead><tr><th>#</th><th>Title</th><th class="num">Served</th><th class="num">Exposed</th><th class="num">Clicked</th><th class="num">CTR</th><th class="num">Played</th><th class="num">Wished</th><th class="num">Purchased</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  `;
  pane.appendChild(sec);
}

async function loadMarsTabActive(root) {
  const container = document.getElementById("view-mars");
  const tabs = container.querySelector(".mars-tabs");
  if (!tabs) return;
  const activeBtn = tabs.querySelector(".mars-tab.active");
  const kind = activeBtn?.dataset.tab || "svod";
  const pane = tabs.querySelector(`[data-pane='${kind}']`);
  const sec = pane?.querySelector(".mars-adultplus");
  if (!sec) return;
  const status = sec.querySelector(".ap-status");
  const force = root.dataset.kpiForceRefresh === "1";
  if (force) delete root.dataset.kpiForceRefresh;
  status.textContent = force ? "강제 재조회 중… (BQ ~15s)" : "불러오는 중…";
  status.dataset.kind = "loading";

  const params = new URLSearchParams({
    start: root.querySelector(".kpi-start").value,
    end: root.querySelector(".kpi-end").value,
    top_n: "50",
  });
  const filters = collectAdultplusFilters("mars");
  for (const [k, v] of Object.entries(filters)) params.set(k, v);
  if (force) params.set("force", "true");
  const lsKey = `ap:mars-${kind}:${params.toString()}`;
  if (!force) {
    const cached = lsGet(lsKey);
    if (cached) {
      renderMarsAdultplus(sec, cached);
      status.textContent = `${cached.period.start} ~ ${cached.period.end} (${cached.period.days}일) · 💾 local`;
      status.dataset.kind = "ok";
      return;
    }
  }
  try {
    const r = await fetch(`/api/kpi/mars/${kind}/summary?${params}`);
    if (!r.ok) {
      const t = await r.text();
      status.textContent = `⚠️ 로드 실패 (${r.status})`;
      status.dataset.kind = "error";
      status.title = t.slice(0, 400);
      return;
    }
    const data = await r.json();
    renderMarsAdultplus(sec, data);
    lsSet(lsKey, data);
    const badge = data.from_cache ? " · ⚡ cache" : "";
    status.textContent = `${data.period.start} ~ ${data.period.end} (${data.period.days}일)${badge}`;
    status.dataset.kind = "ok";
  } catch (exc) {
    status.textContent = `⚠️ 네트워크 오류 — ${exc.message || exc}`;
    status.dataset.kind = "error";
  }
}

// ── Mars × AdultPlus sub-panel ──────────────────────────────────────────
// mars 추천 슬롯 안의 AdultPlus funnel (BQ-only, archive 없음).
// 독립 성인관 (adult 도메인) 과 다른 제품 — mars view 안에 격리된 sub-section.

// galaxy = adult 와 동일 dashboard, 다른 endpoint
function mountGalaxyFunnel(container) {
  if (container.querySelector(".mars-adultplus")) return;
  // mountMarsAdultplus 의 HTML 그대로 재사용 — 다만 header 텍스트만 galaxy 용으로
  mountMarsAdultplus(container);
  const sec = container.querySelector(".mars-adultplus");
  const title = sec.querySelector(".ap-title");
  const sub = sec.querySelector(".ap-sub");
  if (title) title.textContent = "⭐ WatchaPedia (galaxy) funnel";
  if (sub) sub.innerHTML = "사용자 RATE / WISH / SEARCH / CLICK · archive <code>/archive/rec_galaxy/behavior_logs/</code>";
}

async function loadGalaxyFunnel(startInp, endInp, opts = {}) {
  const container = document.getElementById("view-galaxy");
  const sec = container.querySelector(".mars-adultplus");
  if (!sec) return;
  const status = sec.querySelector(".ap-status");
  status.textContent = opts.force ? "강제 재조회 중…" : "불러오는 중…";
  status.dataset.kind = "loading";
  const params = new URLSearchParams({
    start: startInp.value, end: endInp.value, top_n: "50",
  });
  const filters = collectAdultplusFilters("galaxy");
  for (const [k, v] of Object.entries(filters)) params.set(k, v);
  if (opts.force) params.set("force", "true");
  const lsKey = `ap:galaxy:${params.toString()}`;
  if (!opts.force) {
    const cached = lsGet(lsKey);
    if (cached) {
      renderMarsAdultplus(sec, cached);
      status.textContent = `${cached.period.start} ~ ${cached.period.end} (${cached.period.days}일) · 💾 local`;
      status.dataset.kind = "ok";
      return;
    }
  }
  try {
    const r = await fetch(`/api/kpi/galaxy/funnel/summary?${params}`);
    if (!r.ok) {
      const detail = await r.text();
      status.textContent = `⚠️ 로드 실패 (${r.status})`;
      status.dataset.kind = "error";
      status.title = detail.slice(0, 400);
      return;
    }
    const data = await r.json();
    renderMarsAdultplus(sec, data);
    lsSet(lsKey, data);
    const badge = data.from_cache ? " · ⚡ cache" : "";
    status.textContent = `${data.period.start} ~ ${data.period.end} (${data.period.days}일)${badge}`;
    status.dataset.kind = "ok";
  } catch (exc) {
    status.textContent = `⚠️ 네트워크 오류 — ${exc.message || exc}`;
    status.dataset.kind = "error";
  }
}

function mountMarsAdultplus(container) {
  if (container.querySelector(".mars-adultplus")) return;
  const sec = document.createElement("section");
  sec.className = "mars-adultplus";
  // .kpi-main 안에 append — AI 인사이트와 동일 width.
  // (없으면 container 직속으로 fallback)
  const target = container.querySelector(".kpi-main") || container;
  sec.innerHTML = `
    <header class="ap-header">
      <div>
        <h2 class="ap-title">🔞 AdultPlus funnel · mars 추천</h2>
        <p class="ap-sub">mars 본 서비스 안의 성인+ 콘텐츠 노출 funnel · BQ <code>remy_mars_kpi_tod_adultplus_stats</code></p>
      </div>
      <span class="ap-status" aria-live="polite">불러오는 중…</span>
    </header>

    <div class="ap-hero">
      <div class="ap-stat" data-stat="rows_click_ratio">
        <div class="ap-stat-label">Rows: click ratio</div>
        <div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="cells_action_ratio">
        <div class="ap-stat-label">Cells: action ratio</div>
        <div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="unique_users">
        <div class="ap-stat-label">Unique users</div>
        <div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="total_recommends">
        <div class="ap-stat-label">Total recommends</div>
        <div class="ap-stat-value">—</div>
      </div>
      <div class="ap-stat" data-stat="elapsed_median_ms">
        <div class="ap-stat-label">Elapsed: median (ms)</div>
        <div class="ap-stat-value">—</div>
      </div>
    </div>

    <div class="ap-grid-2">
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Exposed · Actioned · ratio</h3><span class="ap-panel-sub">rs 기반</span></div>
        <div class="ap-chart-wrap"><canvas class="ap-ts-actions"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Exposed · Clicked · ratio</h3><span class="ap-panel-sub">rs 기반</span></div>
        <div class="ap-chart-wrap"><canvas class="ap-ts-clicks"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Clicked · Wished · Played · Purchased</h3><span class="ap-panel-sub">cs 기반 + ratios</span></div>
        <div class="ap-chart-wrap"><canvas class="ap-ts-funnel"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Users · Recommends</h3><span class="ap-panel-sub">일별</span></div>
        <div class="ap-chart-wrap"><canvas class="ap-ts-users"></canvas></div>
      </div>
    </div>

    <div class="ap-grid-4">
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Rows: exposed</h3></div>
        <div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-exposed"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Rows: clicked</h3></div>
        <div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-clicked"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Actions</h3></div>
        <div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-actions"></canvas></div>
      </div>
      <div class="ap-panel">
        <div class="ap-panel-head"><h3>Content types</h3><span class="ap-panel-sub">exposed 기준</span></div>
        <div class="ap-chart-wrap ap-pie-wrap"><canvas class="ap-pie-ctypes"></canvas></div>
      </div>
    </div>

    <div class="ap-panel ap-rows-table-panel">
      <div class="ap-panel-head"><h3>Row × funnel</h3><span class="ap-panel-sub">rs.key 별 · 노출률 / 클릭률</span></div>
      <div class="ap-rows-table-wrap">
        <table class="ap-table ap-rows-table">
          <thead><tr>
            <th>#</th>
            <th>Row</th>
            <th class="num">Served</th>
            <th class="num">Exposed</th>
            <th class="num">Expose ratio</th>
            <th class="num">Clicked</th>
            <th class="num">Click ratio</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="ap-panel ap-table-panel">
      <div class="ap-panel-head"><h3>Title × funnel</h3><span class="ap-panel-sub">cs 기반 · TOP 50 · 10행 후 스크롤 (Served/Exposed/Clicked/CTR/Played/Wished/Purchased)</span></div>
      <div style="overflow-x:auto;">
        <table class="ap-table ap-title-table">
          <thead><tr>
            <th>#</th><th>Title</th>
            <th class="num">Served</th>
            <th class="num">Exposed</th>
            <th class="num">Clicked</th>
            <th class="num">CTR</th>
            <th class="num">Played</th>
            <th class="num">Wished</th>
            <th class="num">Purchased</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  `;
  target.appendChild(sec);
}

// ── localStorage cache (브라우저 reload 도 ⚡, 10분 TTL) ─────────────────
const LS_TTL_MS = 10 * 60 * 1000;
function lsGet(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const { ts, data } = JSON.parse(raw);
    if (Date.now() - ts > LS_TTL_MS) { localStorage.removeItem(key); return null; }
    return data;
  } catch { return null; }
}
function lsSet(key, data) {
  try { localStorage.setItem(key, JSON.stringify({ ts: Date.now(), data })); }
  catch { /* quota — ignore */ }
}

async function loadMarsAdultplus(startInp, endInp, opts = {}) {
  const container = document.getElementById("view-adult");
  const sec = container.querySelector(".mars-adultplus");
  if (!sec) return;
  const status = sec.querySelector(".ap-status");
  status.textContent = opts.force ? "강제 재조회 중… (BQ ~15s)" : "불러오는 중…";
  status.dataset.kind = "loading";
  const params = new URLSearchParams({
    start: startInp.value, end: endInp.value, top_n: "50",
  });
  // 필터 (AdultPlus sidebar) — PDF 와 동일 4축
  const filters = collectAdultplusFilters("adult");
  for (const [k, v] of Object.entries(filters)) params.set(k, v);
  if (opts.force) params.set("force", "true");
  // localStorage cache check (force=false 시만)
  const lsKey = `ap:adult:${params.toString()}`;
  if (!opts.force) {
    const cached = lsGet(lsKey);
    if (cached) {
      renderMarsAdultplus(sec, cached);
      status.textContent = `${cached.period.start} ~ ${cached.period.end} (${cached.period.days}일) · 💾 local`;
      status.dataset.kind = "ok";
      return;
    }
  }
  try {
    const r = await fetch(`/api/kpi/mars/adultplus/summary?${params}`);
    if (!r.ok) {
      const detail = await r.text();
      status.textContent = `⚠️ 로드 실패 (${r.status})`;
      status.dataset.kind = "error";
      status.title = detail.slice(0, 400);
      return;
    }
    const data = await r.json();
    renderMarsAdultplus(sec, data);
    lsSet(lsKey, data);  // 다음 reload 까지 보관
    const cacheBadge = data.from_cache ? " · ⚡ cache" : "";
    status.textContent = `${data.period.start} ~ ${data.period.end} (${data.period.days}일)${cacheBadge}`;
    status.dataset.kind = "ok";
  } catch (exc) {
    status.textContent = `⚠️ 네트워크 오류 — ${exc.message || exc}`;
    status.dataset.kind = "error";
  }
}

const AP_PALETTE = [
  "#4dd3c1", "#5b8dee", "#ec5b8e", "#d97757", "#b8d8ff",
  "#f3b095", "#9ba1b3", "#6b5a4a", "#a3e4d7", "#fad7a0",
  "#7fb3d5", "#c39bd3", "#f1948a",
];

function renderMarsAdultplus(sec, data) {
  const h = data.hero || {};
  const ts = data.timeseries || [];
  const pies = data.rows_pie || { exposed: [], clicked: [], actions: [] };
  const titles = data.top_titles || [];

  // ── Hero 5 stats ──
  const statMap = {
    rows_click_ratio: { fmt: "pct", val: h.rows_click_ratio },
    cells_action_ratio: { fmt: "pct", val: h.cells_action_ratio },
    unique_users: { fmt: "num", val: h.unique_users },
    total_recommends: { fmt: "num", val: h.total_recommends },
    elapsed_median_ms: { fmt: "num", val: h.elapsed_median_ms },
  };
  sec.querySelectorAll(".ap-stat").forEach((el) => {
    const key = el.dataset.stat;
    const s = statMap[key] || {};
    const v = s.val;
    el.querySelector(".ap-stat-value").textContent = (v == null) ? "—"
      : (s.fmt === "pct") ? ((v * 100).toFixed(2) + "%")
      : fmt.numFull(v);
  });

  // ── 4 timeseries combo charts ──
  drawApTs(sec.querySelector(".ap-ts-actions"), ts, {
    barDatasets: [{ key: "rs_exposed", label: "Exposed", color: "rgba(91,141,238,0.55)" },
                  { key: "rs_action_cells", label: "Actioned (cells)", color: "rgba(217,119,87,0.75)" }],
    lineDatasets: [{ key: "rs_action_ratio", label: "Ratio", color: "#ec5b8e", pct: true }],
    chartKey: "apTsActions",
  });
  drawApTs(sec.querySelector(".ap-ts-clicks"), ts, {
    barDatasets: [{ key: "rs_exposed", label: "Exposed", color: "rgba(91,141,238,0.55)" },
                  { key: "rs_clicked", label: "Clicked", color: "rgba(217,119,87,0.75)" }],
    lineDatasets: [{ key: "rs_click_ratio", label: "Click ratio", color: "#ec5b8e", pct: true }],
    chartKey: "apTsClicks",
  });
  drawApTs(sec.querySelector(".ap-ts-funnel"), ts, {
    barDatasets: [{ key: "clicked", label: "Clicked", color: "rgba(91,141,238,0.55)" },
                  { key: "wished", label: "Wished", color: "rgba(243,176,149,0.7)" },
                  { key: "played", label: "Played", color: "rgba(77,211,193,0.75)" },
                  { key: "purchased", label: "Purchased", color: "rgba(236,91,142,0.85)" }],
    lineDatasets: [{ key: "cs_play_ratio", label: "Play ratio", color: "#4dd3c1", pct: true },
                   { key: "cs_purchase_ratio", label: "Purchase ratio", color: "#ec5b8e", pct: true },
                   { key: "cs_wish_ratio", label: "Wish ratio", color: "#f3b095", pct: true }],
    chartKey: "apTsFunnel",
  });
  drawApTs(sec.querySelector(".ap-ts-users"), ts, {
    barDatasets: [{ key: "unique_users", label: "Users", color: "rgba(91,141,238,0.65)" }],
    lineDatasets: [{ key: "total_recommends", label: "Recommends", color: "#d97757" }],
    chartKey: "apTsUsers",
  });

  // ── 4 pies (rows × 3 + content types) ──
  drawApPie(sec.querySelector(".ap-pie-exposed"), pies.exposed, "apPieExposed");
  drawApPie(sec.querySelector(".ap-pie-clicked"), pies.clicked, "apPieClicked");
  drawApPie(sec.querySelector(".ap-pie-actions"), pies.actions, "apPieActions");
  drawApPie(sec.querySelector(".ap-pie-ctypes"), data.ctype_pie || [], "apPieCtypes");

  // ── Row × funnel table (rs.key 별) ──
  const rowsTbody = sec.querySelector(".ap-rows-table tbody");
  const rows = data.rows_table || [];
  rowsTbody.innerHTML = rows.length
    ? rows.map((r, i) => `
        <tr>
          <td class="t-rank">${i + 1}</td>
          <td class="t-title">${escapeHtmlD(r.key || "—")}</td>
          <td class="num">${fmt.numFull(r.served)}</td>
          <td class="num">${fmt.numFull(r.exposed)}</td>
          <td class="num">${((r.expose_ratio || 0) * 100).toFixed(0)}%</td>
          <td class="num">${fmt.numFull(r.clicked)}</td>
          <td class="num">${((r.click_ratio || 0) * 100).toFixed(0)}%</td>
        </tr>`).join("")
    : `<tr><td colspan="7" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // ── Title table ──
  const tbody = sec.querySelector(".ap-title-table tbody");
  const maxExp = titles.reduce((m, r) => Math.max(m, r.exposed), 0) || 1;
  tbody.innerHTML = titles.length
    ? titles.map((row, i) => {
        const pct = (row.exposed / maxExp) * 100;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-title">${escapeHtmlD(row.title || row.content || "—")}</td>
            <td class="num">${fmt.numFull(row.served)}</td>
            <td class="num"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">${fmt.numFull(row.exposed)}</span></div></td>
            <td class="num">${fmt.numFull(row.clicked)}</td>
            <td class="num">${((row.click_ratio || 0) * 100).toFixed(1)}%</td>
            <td class="num">${fmt.numFull(row.played)}</td>
            <td class="num">${fmt.numFull(row.wished)}</td>
            <td class="num">${fmt.numFull(row.purchased)}</td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="9" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;
}

function drawApTs(canvas, ts, spec) {
  // Chart.getChart 로 canvas-기반 lookup → SVOD/TVOD/adult sec 간 충돌 방지
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
  if (!ts.length) return;
  const labels = ts.map((r) => r.date);
  const datasets = [];
  for (const b of (spec.barDatasets || [])) {
    datasets.push({
      type: "bar", label: b.label,
      data: ts.map((r) => r[b.key] || 0),
      backgroundColor: b.color, borderRadius: 4,
      categoryPercentage: 0.78, barPercentage: 0.92,
      stack: spec.barDatasets.length > 1 ? "vol" : undefined,
      yAxisID: "y", order: 3,
    });
  }
  for (const l of (spec.lineDatasets || [])) {
    datasets.push({
      type: "line", label: l.label,
      data: ts.map((r) => l.pct ? (r[l.key] || 0) * 100 : (r[l.key] || 0)),
      borderColor: l.color, backgroundColor: "transparent",
      tension: 0.25, pointRadius: 3,
      yAxisID: l.pct ? "y2" : "y",
      order: 1,
    });
  }
  new Chart(canvas, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: { mode: "index", intersect: false },
      },
      scales: {
        y:  { beginAtZero: true, position: "left",
              grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") },
              ticks: { font: { size: 10 } } },
        y2: { beginAtZero: true, position: "right",
              grid: { drawOnChartArea: false },
              ticks: { font: { size: 10 }, callback: (v) => v + "%" } },
        x:  { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } },
      },
    },
  });
}

function drawApPie(canvas, items, chartKey) {
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
  if (!items || !items.length) return;
  const labels = items.map((i) => i.key);
  const values = items.map((i) => i.value);
  const colors = labels.map((_, i) => AP_PALETTE[i % AP_PALETTE.length]);
  new Chart(canvas, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors,
                                 borderColor: "transparent" }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "55%",
      plugins: {
        legend: { position: "right",
                  labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: {
          label: (ctx) => {
            const total = values.reduce((a, b) => a + b, 0) || 1;
            const v = ctx.parsed;
            return `${ctx.label}: ${fmt.numFull(v)} (${((v/total)*100).toFixed(1)}%)`;
          },
        } },
      },
    },
  });
}

function _collectChecked(root, sel) {
  const all = Array.from(root.querySelectorAll(`${sel} input[type=checkbox]`));
  if (!all.length) return [];
  const checked = all.filter((el) => el.checked);
  // 전체 체크 (default) 또는 0개 체크 → 필터 미적용 (서버에 안 보냄, default cache hit)
  if (checked.length === 0 || checked.length === all.length) return [];
  return checked.map((el) => el.value);
}

function selectedContentTypes(root) { return _collectChecked(root, ".aside-ct-list"); }
function selectedActionTypes(root)  { return _collectChecked(root, ".aside-at-list"); }

async function ensureKpiInit(domain) {
  if (!Object.keys(DASH.domains).length) await fetchDomainsMeta();
  mountKpiView(domain);
  if (!DASH.initialized[domain]) {
    DASH.initialized[domain] = true;
    await loadKpi(domain);
  }
}

async function loadKpi(domain) {
  const root = document.getElementById("view-" + domain).querySelector(".kpi-view");
  const start = root.querySelector(".kpi-start").value;
  const end = root.querySelector(".kpi-end").value;
  const cts = selectedContentTypes(root);
  const ats = selectedActionTypes(root);
  const refresh = root.querySelector(".kpi-refresh");
  refresh.disabled = true;
  refresh.textContent = "로딩…";

  const params = new URLSearchParams({ start, end });
  if (cts.length) params.set("content_types", cts.join(","));
  if (ats.length) params.set("action_types", ats.join(","));

  // Track current query so a late series response from an old query
  // doesn't overwrite a newer one.
  const queryKey = `${domain}|${start}|${end}|${cts.join(",")}|${ats.join(",")}`;
  DASH.activeQuery[domain] = queryKey;

  try {
    const r = await fetch(`/api/kpi/${domain}/summary?${params}`);
    if (!r.ok) throw new Error("HTTP " + r.status + " " + (await r.text()));
    const data = await r.json();
    DASH.lastData[domain] = data;  // 테마 토글 시 재렌더용 (refetch/LLM 재호출 회피)
    // store last-loaded params on the view so modal can reuse them
    root.dataset.lastStart = start;
    root.dataset.lastEnd = end;
    root.dataset.lastCts = cts.join(",");
    root.dataset.lastAts = ats.join(",");
    renderKpi(domain, data);

    // Lazy-load daily series in background — populates sparklines + caches
    // for fast modal open.  Don't await; UI stays responsive.
    fetchSeriesBackground(domain, queryKey, params);
    // AI insights also background (LLM call ~3-8s; cached server-side)
    loadInsights(domain);
  } catch (e) {
    const card = root.querySelector(".kpi-cards");
    card.innerHTML = `<div class="kpi-error">로드 실패: ${e.message}</div>`;
  } finally {
    refresh.disabled = false;
    refresh.textContent = "새로고침";
  }

  // ── 도메인별 custom dashboard 로드 — try 밖에서 독립 실행. ──
  // (위 summary fetch 에러나도 custom funnel 은 별도 endpoint 이므로 시도)
  const force = root.dataset.kpiForceRefresh === "1";
  if (force) delete root.dataset.kpiForceRefresh;
  if (domain === "adult") {
    loadMarsAdultplus(root.querySelector(".kpi-start"),
                      root.querySelector(".kpi-end"),
                      { force });
  } else if (domain === "galaxy") {
    loadGalaxyFunnel(root.querySelector(".kpi-start"),
                     root.querySelector(".kpi-end"),
                     { force });
  } else if (domain === "mars") {
    loadMarsTabActive(root);
  }
}

async function fetchSeriesBackground(domain, queryKey, params) {
  try {
    const r = await fetch(`/api/kpi/${domain}/series?${params}`);
    if (!r.ok) return;
    const data = await r.json();
    // If the user changed filters meanwhile, drop the stale result.
    if (DASH.activeQuery[domain] !== queryKey) return;
    DASH.seriesCache[domain] = {
      key: queryKey,
      dates: data.dates,
      series: data.series,
      fmts: data.fmts,
    };
    paintSparklines(domain);
  } catch (e) {
    /* silent — sparklines stay empty */
  }
}

function paintSparklines(domain) {
  const cache = DASH.seriesCache[domain];
  if (!cache) return;
  const root = document.getElementById("view-" + domain).querySelector(".kpi-view");
  if (!root) return;

  // Hero cards — mini sparkline + delta %
  root.querySelectorAll(".kpi-card").forEach((card) => {
    const label = card.dataset.label;
    const fmtKind = cache.fmts[label] || "int";
    const values = cache.series[label] || [];
    const sparkEl = card.querySelector(".kpi-card-spark");
    if (sparkEl) sparkEl.innerHTML = sparkline(values, fmtKind, cache.dates, /*small=*/true);
    const deltaEl = card.querySelector(".kpi-card-delta");
    if (deltaEl && values.length >= 2) {
      const info = deltaInfo(values, fmtKind);
      deltaEl.textContent = info.text;
      deltaEl.classList.remove("up", "down", "flat");
      deltaEl.classList.add(info.cls);
    }
  });

  // Inline KPI table + all-KPI modal table
  const targets = [];
  targets.push(...root.querySelectorAll(".kpi-metric-table tbody tr"));
  const allModal = document.getElementById("kpi-all-modal");
  if (allModal && !allModal.hidden && allModal.dataset.domain === domain) {
    targets.push(...allModal.querySelectorAll(".kpi-metric-table tbody tr"));
  }
  for (const tr of targets) {
    const label = tr.dataset.label;
    const values = cache.series[label] || [];
    const fmtKind = cache.fmts[label] || "int";
    const sparkCell = tr.querySelector(".m-spark");
    if (sparkCell) sparkCell.innerHTML = sparkline(values, fmtKind, cache.dates);
    // last value + delta
    const info = deltaInfo(values, fmtKind);
    const lastCell = tr.querySelector(".m-last");
    const deltaCell = tr.querySelector(".m-delta");
    if (lastCell && info.lastVal !== undefined) {
      lastCell.textContent = fmt.card(info.lastVal, fmtKind);
    }
    if (deltaCell) {
      deltaCell.textContent = info.text;
      deltaCell.classList.remove("up", "down", "flat");
      deltaCell.classList.add(info.cls);
    }
  }
}

function kpiRowHtml(k) {
  // For pct KPIs, show a small inline bar in the value cell.
  let valueHtml = escapeHtmlD(fmt.card(k.value, k.fmt));
  if (k.fmt === "pct") {
    const pct = Math.max(0, Math.min(1, k.value)) * 100;
    valueHtml = `<div class="v-cell"><div class="v-bar" style="width:${pct.toFixed(1)}%"></div><span class="v-num">${valueHtml}</span></div>`;
  }
  return `
    <tr data-kind="${escapeHtmlD(k.fmt)}" data-label="${escapeHtmlD(k.label)}">
      <td class="m-label">${escapeHtmlD(k.label)}</td>
      <td class="m-value">${valueHtml}</td>
      <td class="m-last">—</td>
      <td class="m-delta">—</td>
      <td class="m-spark"><span class="spark-pending">·</span></td>
    </tr>`;
}

function deltaInfo(values, fmt_) {
  // 전일대비 (DoD) — 마지막 일자 vs 직전 일자.
  if (!values || values.length < 2) return { text: "—", cls: "flat" };
  const last = values[values.length - 1];
  const prev = values[values.length - 2];
  const diff = last - prev;
  if (prev === 0 && last === 0) return { text: "—", cls: "flat", lastVal: last };
  const pct = prev !== 0 ? (diff / Math.abs(prev)) * 100 : (last > 0 ? 100 : -100);
  const sign = diff > 0 ? "↑" : diff < 0 ? "↓" : "·";
  const cls = diff > 0.0001 ? "up" : diff < -0.0001 ? "down" : "flat";
  let pctTxt;
  if (Math.abs(pct) >= 100) pctTxt = pct.toFixed(0) + "%";
  else if (Math.abs(pct) >= 10) pctTxt = pct.toFixed(1) + "%";
  else pctTxt = pct.toFixed(2) + "%";
  return { text: `${sign} ${pctTxt.replace("-", "")}`, cls, lastVal: last };
}

function openAllKpiModal(domain) {
  const modal = document.getElementById("kpi-all-modal");
  const kpis = (DASH.fullKpis && DASH.fullKpis[domain]) || [];
  modal.dataset.domain = domain;
  const meta = DASH.domains[domain]?.label || domain;
  const viewRoot = document.getElementById("view-" + domain).querySelector(".kpi-view");
  const start = viewRoot?.dataset.lastStart || "";
  const end = viewRoot?.dataset.lastEnd || "";
  modal.querySelector("#kpi-all-sub").textContent =
    `${meta} · ${shortDate(start)} ~ ${shortDate(end)} · ${kpis.length}개 지표`;

  const tbody = modal.querySelector(".kpi-metric-table tbody");
  tbody.innerHTML = kpis.map((k) => kpiRowHtml(k)).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      // close all-modal first so we don't have two modals stacked
      modal.hidden = true;
      openKpiModal(domain, tr.dataset.label, tr.dataset.kind);
    });
  });
  modal.hidden = false;
  // paint sparklines if cached
  paintSparklines(domain);
}

function shortDate(s) {
  if (!s) return "—";
  // 2026-05-17 → 26-05-17
  return s.slice(2);
}

function daysBetween(start, end) {
  if (!start || !end) return 0;
  const s = new Date(start), e = new Date(end);
  return Math.round((e - s) / 86400000) + 1;
}

function renderKpi(domain, data) {
  const root = document.getElementById("view-" + domain).querySelector(".kpi-view");
  const kpis = data.kpis || [];

  // Replace [start~end] placeholders in panel-sub with actual dates
  const periodTxt = `${shortDate(data.start)}~${shortDate(data.end)}`;
  root.querySelectorAll(".panel-sub").forEach((el) => {
    if (el.textContent.includes("[start~end]")) {
      el.textContent = el.textContent.replace("[start~end]", periodTxt);
    }
  });
  const heroLabels = data.hero_labels && data.hero_labels.length
    ? data.hero_labels
    : ["Total events", "Unique users", "Unique contents"];

  // Hero = exactly the labels chosen by backend per domain, in given order.
  const byLabel = Object.fromEntries(kpis.map((k) => [k.label, k]));
  const hero = heroLabels.map((l) => byLabel[l]).filter(Boolean);
  const restLabels = new Set(heroLabels);
  const rest = kpis.filter((k) => !restLabels.has(k.label));

  const cardWrap = root.querySelector(".kpi-cards");
  cardWrap.innerHTML = hero.map((k) => `
    <div class="kpi-card" style="cursor:pointer" data-kind="${escapeHtmlD(k.fmt)}" data-label="${escapeHtmlD(k.label)}">
      <div class="kpi-card-label">
        <span>${escapeHtmlD(k.label)}</span>
        <span class="kpi-card-delta">—</span>
      </div>
      <div class="kpi-card-value">${escapeHtmlD(fmt.card(k.value, k.fmt))}</div>
      <div class="kpi-card-spark"></div>
    </div>
  `).join("");
  // 클릭 핸들러는 mountKpiView 의 위임 리스너가 처리 (여기서 재바인딩 안 함).

  // Right aside — summary panel + content_type checklist (galaxy) + data source
  renderAside(root, domain, data);

  // KPI metric table — show only the backend-curated priority 5
  const priority = data.table_priority || [];
  const restMap = Object.fromEntries(rest.map((k) => [k.label, k]));
  const tableRows = priority.length
    ? priority.map((l) => restMap[l]).filter(Boolean)
    : rest.slice(0, 5);
  const metricBody = root.querySelector(".kpi-metric-table tbody");
  metricBody.innerHTML = tableRows.map((k) => kpiRowHtml(k)).join("");
  // 행 클릭 → 모달: mountKpiView 의 .kpi-metric-table 위임 리스너가 처리.

  // Stash full KPI list (including hero) for the all-KPI modal
  DASH.fullKpis = DASH.fullKpis || {};
  DASH.fullKpis[domain] = kpis;

  // If series already cached for this query, paint sparklines instantly.
  const cache = DASH.seriesCache[domain];
  const cur = DASH.activeQuery[domain];
  if (cache && cache.key === cur) paintSparklines(domain);

  // Timeseries chart
  const ts = data.timeseries || [];
  drawTimeseries(domain, root.querySelector(".chart-ts"), ts);

  // Action breakdown
  drawActions(domain, root.querySelector(".chart-actions"), data.actions || []);

  // Domain-specific panel visibility from backend `supports` spec — declare
  // BEFORE the table-render block below so we can hide cells per domain.
  const sup = data.supports || {};

  // === 4-col bottom row tables ===
  const ctNames = { "1": "MV", "2": "TV", "4": "BK", "5": "EP", "8": "WT", "10": "AM", "11": "AW" };

  // TOP contents (모든 도메인) — title 있으면 title, 없으면 content_id
  const top = data.top_contents || [];
  const maxEv = top.reduce((m, r) => Math.max(m, r.events), 0) || 1;
  root.querySelector(".top10-contents tbody").innerHTML = top.length
    ? top.map((row, i) => {
        const pct = (row.events / maxEv) * 100;
        const ct = (row.content || "").split(":")[0];
        const label = row.title || row.content;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-content"><span class="ctype-pill" data-ct="${escapeHtmlD(ct)}">${escapeHtmlD(ctNames[ct] || ct)}</span><span class="t-title">${escapeHtmlD(label)}</span></td>
            <td class="t-events"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">${fmt.numFull(row.events)}</span></div></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // TOP genres
  const genres = data.top_genres || [];
  const maxGenreEv = genres.reduce((m, r) => Math.max(m, r.events), 0) || 1;
  root.querySelector(".top10-genres tbody").innerHTML = genres.length
    ? genres.map((row, i) => {
        const pct = (row.events / maxGenreEv) * 100;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-content"><span class="t-title">${escapeHtmlD(row.name)}</span></td>
            <td class="t-events"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">${fmt.numFull(row.events)}</span></div></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // TOP users (활동/소비) — 도메인별 metric 기준
  const userTop = data.top_users || [];
  const maxUserEv = userTop.reduce((m, r) => Math.max(m, r.events), 0) || 1;
  root.querySelector(".top10-users tbody").innerHTML = userTop.length
    ? userTop.map((row, i) => {
        const pct = (row.events / maxUserEv) * 100;
        const label = `user ${row.user_id} · ${row.contents}개 콘텐츠`;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-content"><span class="t-title">${escapeHtmlD(label)}</span></td>
            <td class="t-events"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">${fmt.numFull(row.events)}</span></div></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // TOP MEH (negative feedback) contents — galaxy / mars
  const mehTop = data.top_meh_contents || [];
  const maxMeh = mehTop.reduce((m, r) => Math.max(m, r.meh_count), 0) || 1;
  root.querySelector(".top10-meh-contents tbody").innerHTML = mehTop.length
    ? mehTop.map((row, i) => {
        const pct = (row.meh_count / maxMeh) * 100;
        const ct = (row.content || "").split(":")[0];
        const label = row.title || row.content;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-content"><span class="ctype-pill" data-ct="${escapeHtmlD(ct)}">${escapeHtmlD(ctNames[ct] || ct)}</span><span class="t-title">${escapeHtmlD(label)}</span></td>
            <td class="t-events"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">${fmt.numFull(row.meh_count)}</span></div></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // TOP revenue contents (ADULT) — title 있으면 title
  const revTop = data.top_revenue_contents || [];
  const maxRev = revTop.reduce((m, r) => Math.max(m, r.revenue), 0) || 1;
  root.querySelector(".top10-rev-contents tbody").innerHTML = revTop.length
    ? revTop.map((row, i) => {
        const pct = (row.revenue / maxRev) * 100;
        const label = row.title || row.content;
        return `
          <tr>
            <td class="t-rank">${i + 1}</td>
            <td class="t-content"><span class="t-title">${escapeHtmlD(label)}</span></td>
            <td class="t-events"><div class="ev-cell"><div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div><span class="ev-num">₩${(row.revenue/10000).toFixed(0)}만</span></div></td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;

  // Panel visibility — strong hide (hidden + display:none, CSS/브라우저 override 방지)
  const setHidden = (sel, hide) => {
    const el = root.querySelector(sel);
    if (!el) return;
    el.hidden = !!hide;
    el.style.display = hide ? "none" : "";
  };
  setHidden(".kpi-panel-top", false);          // 모든 도메인 노출
  setHidden(".kpi-panel-genre", !sup.genre);
  setHidden(".kpi-panel-rev-top", !sup.revenue);
  setHidden(".kpi-panel-meh-top", !sup.meh_top);
  setHidden(".kpi-panel-user-top", !sup.user_top);
  setHidden(".kpi-panel-actor", !sup.meta_top);
  setHidden(".kpi-panel-director", !sup.meta_top);

  // Content-type donut (별도 row, ADULT 등 supports=False 면 숨김)
  if (sup.ctype_donut) drawCtypeDonut(domain, root.querySelector(".chart-ctype"), root.querySelector(".donut-legend"), data.content_type_breakdown || []);

  // Domain-specific panel visibility from backend `supports` spec
  setHidden(".kpi-panel-rating", !sup.rating_dist);
  setHidden(".kpi-panel-revenue", !sup.revenue);
  setHidden(".kpi-panel-donut", !sup.ctype_donut);
  setHidden(".kpi-panel-hour", !sup.hourly);
  setHidden(".kpi-panel-pareto", !sup.pareto);

  if (sup.rating_dist) drawRatingDist(domain, root.querySelector(".chart-rating"), data.rating_distribution || [], root.querySelector(".kpi-panel-rating"));
  if (sup.hourly)      drawHourly(domain, root.querySelector(".chart-hour"), data.hourly_activity || []);
  if (sup.pareto)      drawPareto(domain, root.querySelector(".chart-pareto"), data.pareto_curve || []);
  if (sup.revenue)     drawRevenue(domain, root, data.revenue || {});
  if (sup.meta_top)    drawMetaTop(root, domain, data.top_actors || [], data.top_directors || []);

  // Footer line: elapsed time only (file path moved to aside)
  root.querySelector(".kpi-files-inline").textContent = "";
  root.querySelector(".kpi-elapsed").textContent = `집계 ${data.elapsed_ms} ms`;
}

function renderAside(root, domain, data) {
  // Summary panel — match latest label set (DAU was 'Unique users' before)
  const byLabel = Object.fromEntries((data.kpis || []).map((k) => [k.label, k]));
  const ev = byLabel["Total events"]?.value ?? 0;
  const us = (byLabel["active_users"] || byLabel["DAU"] || byLabel["Unique users"])?.value ?? 0;
  const co = byLabel["Unique contents"]?.value ?? 0;
  root.querySelector(".meta-events").textContent = fmt.num(ev);
  root.querySelector(".meta-users").textContent  = fmt.num(us);
  root.querySelector(".meta-contents").textContent = fmt.num(co);
  const days = daysBetween(data.start, data.end);
  root.querySelector(".meta-period").textContent =
    `${shortDate(data.start)}~${shortDate(data.end)} · ${days}일`;

  // Content-type checklist (galaxy / mars)
  buildChecklist({
    root, domain,
    panel: root.querySelector(".aside-ct-panel"),
    list: root.querySelector(".aside-ct-list"),
    resetBtn: root.querySelector(".aside-ct-panel .aside-reset"),
    available: data.available_content_types || [],
    selected: new Set(data.content_types || []),
  });

  // Action-type checklist (모든 도메인)
  buildChecklist({
    root, domain,
    panel: root.querySelector(".aside-at-panel"),
    list: root.querySelector(".aside-at-list"),
    resetBtn: root.querySelector(".aside-at-panel .aside-reset-at"),
    available: (data.available_action_types || []).map((a) => ({ key: a, label: a })),
    selected: new Set(data.action_types || []),
  });

  // Data source (now inside summary panel)
  const src = {
    galaxy: "/archive/rec_galaxy/behavior_logs/",
    mars:   "/archive/user_bert/behavior_logs2/train/",
    adult:  "/archive/rec_adult/behavior_logs/",
  }[domain] || "—";
  const files = data.files_read && data.files_read.length
    ? `${src}\n→ ${data.files_read.join(", ")}`
    : src;
  root.querySelector(".aside-source").textContent = files;
}

// Debounce 헬퍼 — 사용자가 여러 체크박스 빠르게 누르면 마지막에만 fetch
const _DEBOUNCE_TIMERS = {};
function debouncedLoad(domain, ms = 300) {
  if (_DEBOUNCE_TIMERS[domain]) clearTimeout(_DEBOUNCE_TIMERS[domain]);
  _DEBOUNCE_TIMERS[domain] = setTimeout(() => {
    delete _DEBOUNCE_TIMERS[domain];
    loadKpi(domain);
  }, ms);
}

function buildChecklist({ root, domain, panel, list, resetBtn, available, selected }) {
  if (!available || !available.length) { panel.hidden = true; return; }
  panel.hidden = false;
  if (!list.dataset.built) {
    list.innerHTML = available.map((c) => `
      <li>
        <label>
          <input type="checkbox" value="${escapeHtmlD(c.key)}" checked>
          <span>${escapeHtmlD(c.label)}</span>
        </label>
      </li>
    `).join("");
    list.dataset.built = "1";
    list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => debouncedLoad(domain));
    });
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        list.querySelectorAll("input[type=checkbox]").forEach((cb) => { cb.checked = true; });
        debouncedLoad(domain);
      });
    }
  }
  // selected empty → 필터 미적용 == 전체 체크. 명시 set 있으면 그것만.
  const allChecked = !selected || selected.size === 0;
  list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.checked = allChecked ? true : selected.has(cb.value);
  });
}

// ───────── AI insights ─────────
async function loadInsights(domain, force = false) {
  const view = document.getElementById("view-" + domain);
  if (!view) {
    console.warn("[loadInsights] view-" + domain + " not found");
    return;
  }
  const root = view.querySelector(".kpi-view");
  if (!root) {
    console.warn("[loadInsights] .kpi-view not mounted for", domain);
    return;
  }
  const panel = root.querySelector(".kpi-panel-insight");
  if (!panel) {
    console.warn("[loadInsights] insight panel not found for", domain);
    return;
  }
  const status = panel.querySelector(".aside-insight-status");
  const list = panel.querySelector(".aside-insight-list");
  const meta = panel.querySelector(".aside-insight-meta");
  const btn = panel.querySelector(".aside-insight-refresh");

  const start = root.dataset.lastStart || root.querySelector(".kpi-start").value;
  const end = root.dataset.lastEnd || root.querySelector(".kpi-end").value;
  if (!start || !end) return;

  const queryKey = `${domain}|${start}|${end}`;
  if (!force && DASH.activeInsightQuery === queryKey) return;
  DASH.activeInsightQuery = queryKey;

  const hadPrev = list.children.length > 0;
  if (!hadPrev) {
    status.textContent = "분석 중…";
    status.hidden = false;
    meta.textContent = "";
  } else {
    status.hidden = true;
  }
  btn.classList.add("spinning");

  const params = new URLSearchParams({ start, end });
  if (force) params.set("force", "true");
  try {
    const r = await fetch(`/api/kpi/${domain}/insights?${params}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    // drop if the user moved on
    if (DASH.activeInsightQuery !== queryKey) return;
    if (!data.bullets || !data.bullets.length) {
      status.textContent = data.error || "인사이트 생성 실패";
      return;
    }
    status.hidden = true;
    list.innerHTML = data.bullets.map((b) => `<li>${formatInsight(b)}</li>`).join("");
    const model = (data.model || "").replace(/^claude-/, "").replace(/-2\d{7}$/, "");
    const ms = data.elapsed_ms || 0;
    const dur = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
    meta.textContent = `${model} · ${dur}`;
  } catch (e) {
    status.textContent = "에러: " + e.message;
  } finally {
    btn.classList.remove("spinning");
  }
}

function formatInsight(text) {
  // Minimal markdown: **bold** + escape
  const escaped = escapeHtmlD(text);
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function drawTimeseries(domain, canvas, ts) {
  if (DASH.charts[domain]?.ts) DASH.charts[domain].ts.destroy();
  const labels = ts.map((r) => r.date);
  const events = ts.map((r) => r.events);
  const users = ts.map((r) => r.users);
  const ch = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          type: "bar",
          label: "Events",
          data: events,
          backgroundColor: "rgba(77, 211, 193, 0.92)",
          borderRadius: 6,
          borderSkipped: false,
          categoryPercentage: 0.88,
          barPercentage: 0.94,
          yAxisID: "y",
          order: 2,
        },
        {
          type: "line",
          label: "Users",
          data: users,
          borderColor: "#5b8dee",
          backgroundColor: "transparent",
          tension: 0.3,
          pointRadius: 3, pointBackgroundColor: "#5b8dee",
          yAxisID: "y2",
          order: 1,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: "index", intersect: false },
      },
      scales: {
        y:  { beginAtZero: true, position: "left",  grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") } },
        y2: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } },
        x:  { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
      },
    },
  });
  DASH.charts[domain] = { ...(DASH.charts[domain] || {}), ts: ch };
}

const DONUT_PALETTE = [
  "#4dd3c1", "#5b8dee", "#ec5b8e", "#d97757", "#b8d8ff",
  "#f3b095", "#9ba1b3", "#6b5a4a",
];

function drawCtypeDonut(domain, canvas, legendEl, items) {
  DASH.charts[domain] = DASH.charts[domain] || {};
  if (DASH.charts[domain].ctype) DASH.charts[domain].ctype.destroy();
  if (!items.length) {
    if (legendEl) legendEl.innerHTML = `<li style="color:var(--ink-faint)">데이터 없음</li>`;
    return;
  }
  const labels = items.map((i) => i.label);
  const counts = items.map((i) => i.count);
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  const colors = labels.map((_, i) => DONUT_PALETTE[i % DONUT_PALETTE.length]);

  DASH.charts[domain].ctype = new Chart(canvas, {
    type: "doughnut",
    data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const v = item.parsed;
              const share = ((v / total) * 100).toFixed(1);
              return `${item.label}: ${fmt.num(v)} · ${share}%`;
            },
          },
        },
      },
    },
  });

  if (legendEl) {
    legendEl.innerHTML = items.map((it, i) => {
      const share = ((it.count / total) * 100).toFixed(1);
      return `<li>
        <span class="dot" style="background:${colors[i]}"></span>
        <span class="lg-name">${escapeHtmlD(it.label)}</span>
        <span class="lg-value">${share}%</span>
      </li>`;
    }).join("");
  }
}

function drawRatingDist(domain, canvas, items, panel) {
  DASH.charts[domain] = DASH.charts[domain] || {};
  if (DASH.charts[domain].rating) DASH.charts[domain].rating.destroy();
  // ADULT 같이 평점 데이터가 없는 도메인은 패널 자체 숨김
  if (!items.length) { if (panel) panel.hidden = true; return; }
  if (panel) panel.hidden = false;
  const labels = items.map((i) => `★${i.rating}`);
  const counts = items.map((i) => i.count);
  const max = Math.max(...counts);
  const colors = counts.map((c) => c === max ? "rgba(217,119,87,0.9)" : "rgba(91,141,238,0.65)");
  DASH.charts[domain].rating = new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderRadius: 3, borderSkipped: false }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const it = items[item.dataIndex];
              return `★${it.rating}: ${fmt.num(it.count)} · ${(it.share * 100).toFixed(1)}%`;
            },
          },
        },
      },
      scales: {
        y: { beginAtZero: true, grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") }, ticks: { callback: (v) => fmt.num(v) } },
        x: { grid: { display: false } },
      },
    },
  });
}

function drawHourly(domain, canvas, items) {
  DASH.charts[domain] = DASH.charts[domain] || {};
  if (DASH.charts[domain].hourly) DASH.charts[domain].hourly.destroy();
  if (!items.length) return;
  // Fill 0-23 with zeros if missing
  const byHour = Object.fromEntries(items.map((i) => [i.hour, i.count]));
  const labels = Array.from({ length: 24 }, (_, h) => `${h}시`);
  const counts = Array.from({ length: 24 }, (_, h) => byHour[h] || 0);
  const peak = counts.indexOf(Math.max(...counts));
  const colors = counts.map((_, i) => i === peak ? "rgba(236,91,142,0.9)" : "rgba(77,211,193,0.75)");
  DASH.charts[domain].hourly = new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderRadius: 2, borderSkipped: false }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (item) => `${item.label}: ${fmt.num(item.parsed.y)}` },
        },
      },
      scales: {
        y: { beginAtZero: true, grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") }, ticks: { callback: (v) => fmt.num(v) } },
        x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 8, font: { size: 10 } } },
      },
    },
  });
}

function drawRevenue(domain, root, data) {
  DASH.charts[domain] = DASH.charts[domain] || {};
  if (DASH.charts[domain].revenue) DASH.charts[domain].revenue.destroy();
  if (!data || !data.available) { root.querySelector(".kpi-panel-revenue").hidden = true; return; }
  // Headline cards
  const fmtW = (n) => "₩" + (n >= 10000 ? Math.round(n/10000).toLocaleString() + "만" : n.toLocaleString());
  root.querySelector(".rev-total").textContent = fmtW(data.total_revenue);
  root.querySelector(".rev-arppu").textContent = fmtW(Math.round(data.revenue_per_paying_user || 0));
  root.querySelector(".rev-paying").textContent = (data.paying_users || 0).toLocaleString();

  // Daily revenue bar chart with above-bar labels
  const daily = data.daily_revenue || [];
  const labels = daily.map((d) => d.date);
  const revs = daily.map((d) => d.revenue);
  const canvas = root.querySelector(".chart-revenue");
  const labelPlugin = {
    id: "revBarLabels",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const ds = chart.getDatasetMeta(0).data;
      ctx.save();
      ctx.font = "600 11px Pretendard, sans-serif";
      ctx.textAlign = "center";
      ctx.fillStyle = themeColor("--ink", "#e6e8ee");
      ds.forEach((bar, i) => {
        const v = revs[i];
        if (v == null) return;
        const txt = `₩${Math.round(v / 10000).toLocaleString()}만`;
        ctx.fillText(txt, bar.x, bar.y - 6);
      });
      ctx.restore();
    },
  };
  DASH.charts[domain].revenue = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "일자별 매출",
        data: revs,
        backgroundColor: "rgba(217,119,87,0.85)",
        borderRadius: 5,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 20 } },   // 라벨 공간
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const d = daily[item.dataIndex];
              return [`매출 ${fmtW(d.revenue)}`, `구매 ${d.purchases}건 · ${d.users}명`];
            },
          },
        },
      },
      scales: {
        y: { beginAtZero: true, grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") },
             ticks: { callback: (v) => fmtW(v) } },
        x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 8, font: { size: 10 } } },
      },
    },
    plugins: [labelPlugin],
  });
}

function drawMetaTop(root, domain, actors, directors) {
  // 도메인별 가중치 기준 명확히
  const weightLabel = domain === "adult"
    ? "기간 RENTAL+POSSESSION events 가중"
    : "기간 events 가중";
  root.querySelectorAll(".kpi-panel-actor .panel-sub, .kpi-panel-director .panel-sub")
    .forEach((el) => { el.textContent = weightLabel; });

  const renderRows = (rows, tbodyEl, fallbackPrefix) => {
    if (!rows.length) {
      tbodyEl.innerHTML = `<tr><td colspan="3" style="color:var(--ink-faint); text-align:center; padding:14px">데이터 없음</td></tr>`;
      return;
    }
    const max = rows.reduce((m, r) => Math.max(m, r.count), 0) || 1;
    tbodyEl.innerHTML = rows.map((r, i) => {
      const pct = (r.count / max) * 100;
      // label 우선 (galaxy/mars), 없으면 ID (adult)
      const display = r.label ? r.label : `${fallbackPrefix} #${r.meta_id}`;
      return `
        <tr>
          <td class="t-rank">${i + 1}</td>
          <td class="t-content"><span class="t-title">${escapeHtmlD(display)}</span></td>
          <td class="t-events">
            <div class="ev-cell">
              <div class="ev-bar-wrap"><div class="ev-bar" style="width:${pct.toFixed(1)}%"></div></div>
              <span class="ev-num">${fmt.numFull(r.count)}</span>
            </div>
          </td>
        </tr>`;
    }).join("");
  };
  renderRows(actors, root.querySelector(".top10-actors tbody"), "Actor");
  renderRows(directors, root.querySelector(".top10-directors tbody"), "Director");
}

function drawPareto(domain, canvas, items) {
  DASH.charts[domain] = DASH.charts[domain] || {};
  if (DASH.charts[domain].pareto) DASH.charts[domain].pareto.destroy();
  if (!items.length) return;
  const labels = items.map((i) => `${(i.top_pct * 100).toFixed(0)}%`);
  const shares = items.map((i) => i.share * 100);
  DASH.charts[domain].pareto = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: shares,
        borderColor: themeColor("--accent", "#d97757"),
        backgroundColor: "rgba(217,119,87,0.15)",
        fill: true,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: themeColor("--accent", "#d97757"),
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (item) => `상위 ${item.label} 콘텐츠 → ${item.parsed.y.toFixed(1)}% 점유` },
        },
      },
      scales: {
        y: { beginAtZero: true, max: 100, grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") }, ticks: { callback: (v) => v + "%" } },
        x: { grid: { display: false }, title: { display: true, text: "콘텐츠 상위 비율", color: themeColor("--ink-faint", "#5e6478"), font: { size: 10 } } },
      },
    },
  });
}

function drawActions(domain, canvas, actions) {
  if (DASH.charts[domain]?.actions) DASH.charts[domain].actions.destroy();
  const labels = actions.map((a) => a.label);
  const counts = actions.map((a) => a.count);
  const bg = counts.map((_, i) => (i === 0 ? "rgba(236, 91, 142, 0.88)" : "rgba(77, 211, 193, 0.78)"));
  // Inline value-label plugin — print count + share% right after each bar
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  const valueLabelPlugin = {
    id: "actionValueLabels",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const ds = chart.getDatasetMeta(0).data;
      ctx.save();
      ctx.font = "600 11px Pretendard, sans-serif";
      ctx.textBaseline = "middle";
      ctx.fillStyle = themeColor("--ink", "#e6e8ee");
      ds.forEach((bar, i) => {
        const v = counts[i];
        const share = ((v / total) * 100).toFixed(1);
        const text = `${fmt.num(v)} · ${share}%`;
        ctx.fillText(text, bar.x + 6, bar.y);
      });
      ctx.restore();
    },
  };
  const ch = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{ data: counts, backgroundColor: bg, borderRadius: 4, borderSkipped: false }],
    },
    options: {
      indexAxis: "y",
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 90 } },     // room for value labels
      categoryPercentage: 0.78,
      barPercentage: 0.92,
      plugins: { legend: { display: false }, tooltip: { displayColors: false } },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") },
          ticks: { callback: (v) => fmt.num(v) },
        },
        y: { grid: { display: false }, ticks: { font: { weight: "600" } } },
      },
    },
    plugins: [valueLabelPlugin],
  });
  DASH.charts[domain] = { ...(DASH.charts[domain] || {}), actions: ch };
}

// ───────── KPI detail modal ─────────
function openKpiModal(domain, label, kind) {
  const modal = document.getElementById("kpi-modal");
  modal.dataset.domain = domain;
  modal.dataset.label = label;
  modal.dataset.kind = kind;

  modal.querySelector(".kpi-modal-title").textContent = label;
  modal.querySelector(".kpi-modal-domain").textContent = (DASH.domains[domain]?.label || domain).split(" ")[0];

  // Pre-fill date range from the current view's last loaded range
  const viewRoot = document.getElementById("view-" + domain).querySelector(".kpi-view");
  const start = viewRoot.dataset.lastStart || viewRoot.querySelector(".kpi-start").value;
  const end = viewRoot.dataset.lastEnd || viewRoot.querySelector(".kpi-end").value;
  const range = DASH.domains[domain]?.range || {};
  const startInp = modal.querySelector(".kpi-modal-start");
  const endInp = modal.querySelector(".kpi-modal-end");
  startInp.value = start; endInp.value = end;
  if (range.min) { startInp.min = range.min; endInp.min = range.min; }
  if (range.max) { startInp.max = range.max; endInp.max = range.max; }

  modal.hidden = false;

  // If we already have cached series for the current view query, render
  // instantly without refetching.
  const cache = DASH.seriesCache[domain];
  const cts = viewRoot.dataset.lastCts || "";
  const viewKey = `${domain}|${start}|${end}|${cts}`;
  if (cache && cache.key === viewKey && cache.series[label]) {
    renderModalChart(label, kind, cache.dates, cache.series[label], 0);
  } else {
    fetchModalSeries(domain, label, kind, start, end, cts);
  }
}

function closeKpiModal() {
  const modal = document.getElementById("kpi-modal");
  modal.hidden = true;
  if (DASH.modalChart) { DASH.modalChart.destroy(); DASH.modalChart = null; }
}

async function fetchModalSeries(domain, label, kind, start, end, cts) {
  const modal = document.getElementById("kpi-modal");
  const refresh = modal.querySelector(".kpi-modal-refresh");
  const elapsedEl = modal.querySelector(".kpi-modal-elapsed");
  refresh.disabled = true; refresh.textContent = "조회 중…";
  elapsedEl.textContent = "";
  const params = new URLSearchParams({ start, end, label });
  if (cts) params.set("content_types", cts);
  try {
    const r = await fetch(`/api/kpi/${domain}/series?${params}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    renderModalChart(data.label, data.fmt || kind, data.dates, data.values, data.elapsed_ms);
  } catch (e) {
    elapsedEl.textContent = "로드 실패: " + e.message;
  } finally {
    refresh.disabled = false; refresh.textContent = "조회";
  }
}

function renderModalChart(label, kind, dates, values, elapsedMs) {
  const modal = document.getElementById("kpi-modal");
  const sumEl = modal.querySelector(".kpi-modal-summary-value");
  // Display headline = mean for ratio KPIs, sum for counts
  let summary;
  if (kind === "pct" || kind === "f2") {
    const m = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
    summary = fmt.card(m, kind);
    modal.querySelector(".kpi-modal-summary-label").textContent = "평균";
  } else {
    const s = values.reduce((a, b) => a + b, 0);
    summary = fmt.card(s, kind);
    modal.querySelector(".kpi-modal-summary-label").textContent = "합계";
  }
  sumEl.textContent = summary;
  if (elapsedMs) {
    modal.querySelector(".kpi-modal-elapsed").textContent = `${elapsedMs} ms`;
  }

  if (DASH.modalChart) DASH.modalChart.destroy();
  const ctx = document.getElementById("kpi-modal-chart");
  const color = kind === "pct" ? "rgba(77,211,193,0.85)"
              : kind === "f2"  ? "rgba(184,216,255,0.85)"
              :                  "rgba(155,161,179,0.85)";
  DASH.modalChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: dates,
      datasets: [{
        label, data: values,
        backgroundColor: color, borderRadius: 4, borderSkipped: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => `${label}: ${fmt.card(item.parsed.y, kind)}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: { color: themeColor("--grid", "rgba(255,255,255,0.04)") },
          ticks: {
            callback: (v) => kind === "pct" ? (v * 100).toFixed(1) + "%" : fmt.num(v),
          },
        },
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
      },
    },
  });
}

// Wire modal events (once)
document.addEventListener("DOMContentLoaded", () => {
  const detail = document.getElementById("kpi-modal");
  const all = document.getElementById("kpi-all-modal");

  detail.querySelector(".kpi-modal-close").addEventListener("click", closeKpiModal);
  detail.addEventListener("click", (e) => { if (e.target === detail) closeKpiModal(); });
  detail.querySelector(".kpi-modal-refresh").addEventListener("click", () => {
    const domain = detail.dataset.domain;
    const label = detail.dataset.label;
    const kind = detail.dataset.kind;
    const start = detail.querySelector(".kpi-modal-start").value;
    const end = detail.querySelector(".kpi-modal-end").value;
    const viewRoot = document.getElementById("view-" + domain).querySelector(".kpi-view");
    const cts = viewRoot.dataset.lastCts || "";
    fetchModalSeries(domain, label, kind, start, end, cts);
  });

  all.querySelector(".kpi-modal-close").addEventListener("click", () => { all.hidden = true; });
  all.addEventListener("click", (e) => { if (e.target === all) all.hidden = true; });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!detail.hidden) closeKpiModal();
    else if (!all.hidden) all.hidden = true;
  });
});

function sparkline(values, kind, dates, small = false) {
  if (!values || values.length < 2) return "";
  const W = small ? 100 : 110;
  const H = small ? 24 : 22;
  const P = 2;
  const vmin = Math.min(...values);
  const vmax = Math.max(...values);
  const span = vmax - vmin || 1;
  const step = (W - P * 2) / (values.length - 1);
  const pts = values.map((v, i) => {
    const x = P + step * i;
    const y = H - P - ((v - vmin) / span) * (H - P * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const lx = P + step * (values.length - 1);
  const ly = H - P - ((values[values.length - 1] - vmin) / span) * (H - P * 2);
  // Color + theme-aware: read CSS vars so light theme uses brand colours.
  const colorMap = {
    pct: themeColor("--teal", "#4dd3c1"),
    f2:  themeColor("--blue", "#5b8dee"),
    int: themeColor("--ink-faint", "#9ba1b3"),
  };
  const color = colorMap[kind] || colorMap.int;
  // Area fill (small=true uses gradient under line)
  const area = small ? `<defs><linearGradient id="g-${kind}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon fill="url(#g-${kind})" points="${P},${H - P} ${pts.join(" ")} ${lx.toFixed(1)},${H - P}"/>` : "";
  const tooltipLines = (dates || []).map((d, i) => `${d}: ${fmt.card(values[i], kind)}`);
  const title = tooltipLines.join("\n");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%" height="${H}" class="spark">
    <title>${escapeHtmlD(title)}</title>
    ${area}
    <polyline fill="none" stroke="${color}" stroke-width="${small ? 1.5 : 1.4}" points="${pts.join(" ")}"/>
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="${small ? 1.8 : 2}" fill="${color}"/>
  </svg>`;
}

function escapeHtmlD(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ───────── boot ─────────
(async function boot() {
  // pick last view or default to galaxy
  let initial = "galaxy";
  try {
    const v = localStorage.getItem("mocha:view");
    if (["galaxy", "mars", "adult", "agent"].includes(v)) initial = v;
  } catch {}
  showView(initial);
})();
