# MOCHA ☕ — 자연어로 묻는 Watcha 데이터 분석 AI

Watcha 사내 데이터 분석을 자연어로 도와주는 AI 어시스턴트. `eda` 플러그인을 백엔드로 사용하는 챗봇 UI.

## 구조

```
mocha/
├── main.py              # FastAPI 백엔드 + Claude Agent SDK
├── plugins/eda/         # vendored eda plugin (frograms/watcha-claude-plugins)
├── static/              # chat UI (vanilla HTML/JS/CSS)
├── migrations/001_init.sql
├── Dockerfile
└── requirements.txt
```

## 로컬 개발

```bash
pip install --break-system-packages -r requirements.txt
PORT=$DEV_PORT python3 main.py
```

헬스체크: `curl http://localhost:$DEV_PORT/health`

## 배포

`feature/*` 브랜치에서 PR → main 머지 시 `mocha.watcha.io`로 자동 배포.
