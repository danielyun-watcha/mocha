// MOCHA i18n — minimal vanilla JS swap.
// Element 에 `data-i18n="key.path"` 속성. 키는 STRINGS 의 dot-path.
// Locale 변경: setLocale('en') → 모든 [data-i18n] 텍스트 즉시 갱신.
// localStorage.mocha_locale 에 저장 → 새로고침 후에도 유지.

const STRINGS = {
  ko: {
    rail: {
      dashboard: "대시보드",
      agent: "MOCHA",
      logout: "로그아웃",
    },
    dashboard: {
      title: "대시보드",
      domain_galaxy: "피디아",
      domain_mars: "왓챠",
      domain_adult: "성인관",
      period_7d: "최근 7일",
      period_30d: "최근 30일",
    },
    chat: {
      send: "보내기",
      placeholder: "질문을 입력하세요…",
      thinking: "생각 중…",
      newsession: "새 대화",
    },
    common: {
      loading: "로딩 중…",
      retry: "재시도",
      error: "오류 발생",
    },
  },
  en: {
    rail: {
      dashboard: "Dashboard",
      agent: "MOCHA",
      logout: "Logout",
    },
    dashboard: {
      title: "Dashboard",
      domain_galaxy: "Pedia",
      domain_mars: "Watcha",
      domain_adult: "Adult",
      period_7d: "Last 7 days",
      period_30d: "Last 30 days",
    },
    chat: {
      send: "Send",
      placeholder: "Ask anything…",
      thinking: "Thinking…",
      newsession: "New chat",
    },
    common: {
      loading: "Loading…",
      retry: "Retry",
      error: "Error",
    },
  },
};

function _get(obj, path) {
  return path.split(".").reduce((o, k) => (o && k in o ? o[k] : null), obj);
}

let _locale = localStorage.getItem("mocha_locale") || "ko";

window.t = function (key) {
  const v = _get(STRINGS[_locale] || STRINGS.ko, key);
  return v ?? key;  // fallback: key 그대로 (개발 중 누락 발견용)
};

window.setLocale = function (loc) {
  if (!(loc in STRINGS)) return;
  _locale = loc;
  localStorage.setItem("mocha_locale", loc);
  document.documentElement.lang = loc;
  applyI18n();
};

window.getLocale = function () {
  return _locale;
};

function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const val = t(key);
    if (val) el.textContent = val;
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    const val = t(key);
    if (val) el.setAttribute("placeholder", val);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.lang = _locale;
  applyI18n();
});

window.applyI18n = applyI18n;
