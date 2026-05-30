# DORA Metrics Platform (DORA 指標平台)

端對端的工程效能量測平台，採用 DORA（DevOps Research and Assessment）指標，並原生整合 **GitHub** 與 **Claude Code AI 遙測**。

[![CI](https://github.com/timwukp/dora-metrics-platform/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![CodeQL](https://github.com/timwukp/dora-metrics-platform/actions/workflows/codeql.yml/badge.svg)](.github/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> [English version](README.md)

## 為什麼用 DORA 指標？

大多數工程團隊每天都在寫程式、發 PR、做部署，但卻無法回答最基本的問題：

> *我們真的有變快嗎？品質是在進步還是退步？跟業界比起來，我們的表現如何？*

**DORA 指標**（來自 Google Cloud 的 DevOps Research and Assessment 團隊）是業界公認衡量軟體交付效能的標準。基於超過 7 年、橫跨 36,000+ 名專業人員的研究，數據顯示表現優異的團隊：

- 部署頻率是低表現團隊的 **973 倍**
- 故障恢復速度快 **6,570 倍**
- 變更失敗率低 **3 倍**
- 程式碼從 commit 到上線的速度快 **6,570 倍**

這不是虛榮指標。研究直接證實 DORA 表現與**商業成果**高度相關：營收成長、獲利能力、市場佔有率、以及客戶滿意度。

### DORA 衡量什麼？對企業有什麼幫助？

| 指標 | 告訴你什麼 | 商業影響 |
|------|-----------|----------|
| **部署頻率** (Deployment Frequency) | 團隊多常把價值交付給使用者 | 更快的上市時間、更短的回饋循環 |
| **變更前置時間** (Lead Time for Changes) | 從想法到上線要多久 | 競爭敏捷度、降低機會成本 |
| **變更失敗率** (Change Failure Rate) | 部署多常造成問題 | 客戶信任、工程信心、減少重工成本 |
| **平均恢復時間** (Mean Time to Recovery) | 出事後多快能恢復 | 營收保護、SLA 合規、客戶留存 |

### 這個平台解決什麼問題？

沒有量測平台的團隊，通常會掉進兩個陷阱之一：

1. **盲飛** — 沒有交付效能的數據。改善都是感覺。領導層無法區分「我們很忙」和「我們真的交付更快了」之間的差別。

2. **Excel 報表** — 有人手動從 GitHub、Jira、PagerDuty 拉數據做季度報告。等報告做好時，數據已經過時且無法即時行動。

這個平台提供**自動化、即時的 DORA 指標**，直接對接你現有的工具（GitHub、CI/CD、事件管理系統）。不需要手動輸入數據、不需要 Excel。團隊每週都能看到自己的表現、及早發現退步、並追蹤流程改善的效果。

### 在 Scrum 團隊中如何應用？

DORA 指標和 Scrum 天然互補。Scrum 提供了固定節奏的迭代框架，DORA 提供了衡量交付效能的客觀數據。兩者結合，讓 Sprint Retrospective 從「我覺得」變成「數據顯示」。

**與 Scrum 儀式的結合：**

| Scrum 儀式 | DORA 如何幫助 | 怎麼用這個平台 |
|------------|--------------|---------------|
| **Sprint Planning** | 參考過去的 Lead Time 和部署頻率，更準確評估團隊吞吐量 | 設定 `days=14` 查看上個 Sprint 的數據作為 baseline |
| **Sprint Review** | 用部署頻率展示實際交付量（不只是 story points） | Dashboard 首頁的 Deployment Frequency 卡片 |
| **Sprint Retrospective** | 定位瓶頸：coding 太慢？review 卡住？部署流程有問題？ | Timeline 趨勢圖 + Lead Time breakdown（coding vs review time） |
| **跨 Sprint 改善追蹤** | 追蹤改善是否持續跨多個 Sprint | 週趨勢圖覆蓋多個 Sprint |

**實際使用建議：**

1. **每個 Retro 打開 Dashboard** — 設定時間範圍為上個 Sprint（例如 14 天）。看四個 DORA 指標有沒有退步。特別關注 Lead Time breakdown：如果 review time 佔了 70%，問題不是開發太慢，而是 code review 流程需要優化。

2. **用 DORA 級別設定漸進目標** — 不要一步到 Elite，從 baseline 出發。例如：「連續 3 個 Sprint 把 Lead Time 從 Medium（1 週）降到 High（1 天）」。

3. **部署頻率作為 Sprint 健康度指標** — 如果突然下降，可能代表工作拆分不夠細、PR 太大、或者有阻塞。趨勢圖可以跨 Sprint 比較，看模式而不是噪音。

4. **DORA 是團隊改善工具，不是績效考核** — DORA 研究團隊明確指出：這些指標用來幫助團隊 inspect & adapt，不是用來評比個人。這與 Scrum 的核心精神一致 — 聚焦在流程改善，不是責怪個人。

**DORA 級別參考（作為改善目標，不是考核標準）：**

| 級別 | 部署頻率 | 變更前置時間 | 變更失敗率 | 恢復時間 |
|------|---------|-------------|-----------|---------|
| Elite | 每天多次 | < 1 小時 | < 5% | < 1 小時 |
| High | 每天到每週 | 1 天 - 1 週 | 5-10% | < 1 天 |
| Medium | 每週到每月 | 1 週 - 1 個月 | 10-15% | 1 天 - 1 週 |
| Low | 每月以上 | > 1 個月 | > 15% | > 1 週 |

大多數團隊從 Medium 開始。目標是每幾個 Sprint 就往上提升一級，而不是一步到位。

### 誰受益？

| 角色 | 從中獲得什麼 |
|------|-------------|
| **工程主管 / VP of Engineering** | 用數據驅動關於團隊能力、投資決策、改善計畫的對話 |
| **平台 / DevOps 團隊** | 驗證基礎設施投資（CI 加速、部署自動化、可觀測性）是否真的改善了交付 |
| **產品開發團隊** | 自助式儀表板追蹤自己的趨勢，不用等季度報告 |
| **高階主管** | 把工程投資與交付吞吐量、可靠性直接關聯 |

## 功能概述

透過 Dashboard 回答團隊的四個核心問題：

| DORA 指標 | 問題 |
|-----------|------|
| 部署頻率 (Deployment Frequency) | 我們多常出貨？ |
| 變更前置時間 (Lead Time for Changes) | 從 commit 到上線要多久？ |
| 變更失敗率 (Change Failure Rate) | 部署多常出問題？ |
| 平均恢復時間 (Mean Time to Recovery) | 出事後多快能恢復？ |

同時呈現 **AI 輔助開發**的信號（來自 Claude Code），包括 session 數、接受/拒絕率、代碼行數、成本，讓你能關聯 AI 使用量與交付指標。

### 四個指標之外的延伸功能

Dashboard 還提供：

- **Sprint 對齊視圖** — 透過設定 `DORA_SPRINT_SCHEDULE="<起始日期>:<sprint 天數>"` 啟用 sprint 選單；未設定時退回「最近 N 天」。
- **DORA 退步告警** — 為每個 repo / 指標定義規則；每天的評估器會在閾值被突破，且（選配）相對於前一個等長視窗變動超過 `change_pct` 時觸發。Slack、Email channel 預設為 stub 模式。內建 7 天去重視窗，避免疲勞轟炸。
- **每週 DORA 等級快照** — 用 heatmap 呈現過去 26 週每個指標的等級（Elite / High / Medium / Low）漂移。每筆快照以 `(repo, metric, week_start)` 為唯一鍵冪等寫入，若某天的排程跳過會自動補回。
- **事件管理 webhook 接收器** — PagerDuty 與 OpsGenie 推送事件生命週期事件（HMAC-SHA256 驗章、防重放）。MTTR 改用真實的 `triggered → resolved` 時間戳，不再倚賴 hotfix PR 的近似值。
- **Retro markdown 匯出** — 一鍵下載 `dora-retro-<時間區間>.md`，包含主要指標、分解資訊、以及規則化的討論建議（高 CFR、review 主導 lead time 等）。
- **跨團隊比對頁** — 為每個設定的 repo 顯示方向性箭頭（↑/↓/→），目的是發現**共同瓶頸**，而不是排名團隊。

## 系統架構

```
GitHub (webhook + REST polling)  ──┐
GitHub Actions (CI/CD)             ├──►  FastAPI 後端  ──►  PostgreSQL
Claude Code (Admin API + OTel)     ┤         │
事件管理來源（選配）                  ┘         ▼
                                       React 儀表板 (Vite + Tailwind + Recharts)
```

完整架構文件：[docs/architecture.md](docs/architecture.md)
威脅模型與安全強化：[SECURITY.md](SECURITY.md) 和 [docs/SECURITY-HARDENING.md](docs/SECURITY-HARDENING.md)

## 快速開始（Docker Compose）

```bash
# 1. 配置環境變數
cp backend/.env.example .env
python -c "import secrets; print('DORA_GITHUB_WEBHOOK_SECRET=' + secrets.token_hex(32))" >> .env
python -c "import secrets; print('DORA_API_KEY=' + secrets.token_urlsafe(48))" >> .env
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))" >> .env
# 編輯 .env：設定 DORA_GITHUB_TOKEN 和 DORA_GITHUB_REPOS

# 2. 啟動
docker compose up -d --build

# 3. 開啟瀏覽器
open http://localhost:3000
```

Compose 檔案**拒絕啟動**如果必要的 secrets 沒有設定 — 這是設計上的安全機制。

## 本地開發

```bash
# 後端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填入真實的設定值
uvicorn app.main:app --reload

# 前端
cd frontend && npm ci && npm run dev
```

## 部署到 AWS EKS

參閱 [docs/EKS-DEPLOY.md](docs/EKS-DEPLOY.md) 取得完整的安全部署指南（RDS、IRSA、External Secrets、ALB+ACM、WAF、NetworkPolicy）。

簡短版本：

```bash
# 建置並推送映像
aws ecr create-repository --repository-name dora-backend
aws ecr create-repository --repository-name dora-frontend
docker build -f infra/docker/Dockerfile.backend  -t $ECR/dora-backend:$TAG .
docker build -f infra/docker/Dockerfile.frontend -t $ECR/dora-frontend:$TAG .
docker push $ECR/dora-backend:$TAG && docker push $ECR/dora-frontend:$TAG

# 部署（先替換 manifests 中的環境變數）
kubectl apply -k infra/k8s
```

## DORA 指標資料來源

| 指標 | 主要來源 | 備援來源 |
|------|---------|---------|
| 部署頻率 | GitHub Deployments API | 合併到預設分支的 PR |
| 變更前置時間 | PR `first_commit_at` → `merged_at` | PR `created_at` → `merged_at` |
| 變更失敗率 | main 上的 CI 失敗率 + revert PR | Revert/hotfix 比率 |
| 平均恢復時間 | 事件管理 webhooks | Hotfix PR `created_at` → `merged_at` |
| AI 貢獻 | Claude Code Admin API (`sk-ant-admin-*`) | OpenTelemetry collector |

### 不只是 GitHub 數據：你需要接入兩個額外信號

如果你只指向一個 GitHub repo，Dashboard 上所有數字都只來自 GitHub 數據 — 四個 DORA 指標中有兩個使用的是**代理值**而非真實數據。要取得有意義的數字，請接入兩個額外來源：

1. **真實的部署事件** — 不要依賴合併 PR 作為部署代理。
   讓你的 CI/CD 在真正部署到 production 時呼叫 `POST /api/v1/deployments`（或使用 GitHub Deployments API）。否則**部署頻率**計算的是合併數（不是發佈數），**變更前置時間**衡量的是 `first_commit → merged_at` 而非 `first_commit → live_in_prod`。

2. **事件來源** — 接入 PagerDuty / OpsGenie / 你的 on-call 工具。
   沒有真實事件數據時，**MTTR** 只能用「hotfix PR 開啟到合併的時間」作為近似值（`is_hotfix` 透過 PR 標題/分支關鍵字偵測）。真實的事件時間戳能給你真正的 `偵測 → 解決` 恢復時間。

在兩者都接入之前，請把 Dashboard 當作**方向性信號** — 適合觀察趨勢，但不適合與 DORA 公開研究的隊列做基準比較。

## API 端點

所有 `GET /api/v1/metrics/*` 是公開唯讀。變更型端點需要 `X-API-Key`。Webhook 需要 HMAC-SHA256 簽章。

| 端點 | 認證方式 |
|------|---------|
| `GET /health` | 無 |
| `GET /api/v1/metrics/dora` | 無 |
| `GET /api/v1/metrics/{deploy-freq,lead-time,change-fail,mttr,timeline}` | 無 |
| `GET /api/v1/metrics/claude-code` | 無 |
| `GET /api/v1/metrics/level-history` | 無 |
| `GET /api/v1/reviews` | 無 |
| `GET /api/v1/repos` | 無 |
| `GET /api/v1/sprints` | 無 |
| `GET /api/v1/reports/retro` | 無 |
| `GET /api/v1/alerts/rules` / `/alerts/events` | 無 |
| `POST /api/v1/collect/github` | `X-API-Key` |
| `POST /api/v1/collect/claude-code` | `X-API-Key` |
| `POST /api/v1/collect/level-snapshots` | `X-API-Key` |
| `POST /api/v1/alerts/rules` / `DELETE /alerts/rules/{id}` | `X-API-Key` |
| `POST /api/v1/alerts/evaluate` | `X-API-Key` |
| `POST /api/v1/webhooks/github` | `X-Hub-Signature-256` HMAC |
| `POST /api/v1/webhooks/pagerduty` | `X-PagerDuty-Signature` HMAC（選配） |
| `POST /api/v1/webhooks/opsgenie` | `X-OpsGenie-Token`（選配） |

Repo 查詢參數會驗證是否在 `DORA_GITHUB_REPOS` 設定中 — 無法查詢未設定追蹤的 repo。

### 新功能對應的設定項

| 設定 | 用途 | 預設值 |
|------|------|--------|
| `DORA_SPRINT_SCHEDULE` | `<起始日期>:<sprint 天數>`（例：`2026-01-06:14`）。未設定時隱藏 sprint 選單。 | 未設定 |
| `DORA_ALERTS_ENABLED` | 告警分派的總開關。`false` 時 channel 只 stub-log，不真的送出。 | `false` |
| `DORA_ALERTS_SLACK_WEBHOOK` | Slack incoming-webhook URL。 | 未設定 |
| `DORA_ALERTS_EMAIL_TO` / `DORA_ALERTS_SMTP` | Email 收件人 + `host:port`。trial 模式下 SMTP 寄送是預留 hook。 | 未設定 |
| `DORA_PAGERDUTY_WEBHOOK_SECRET` | PagerDuty V3 webhook 訂閱用的 HMAC secret。未設定 = 接受未簽章請求（僅供開發）。 | 未設定 |
| `DORA_OPSGENIE_WEBHOOK_SECRET` | 用來比對 `X-OpsGenie-Token` 的 token。 | 未設定 |
| `DORA_INCIDENT_DEFAULT_REPO` | 當 webhook payload 缺少 service→repo 對應時，事件歸屬的 repo。 | 第一個設定的 repo |

## 安全性

簡短摘要；完整政策請參閱 [SECURITY.md](SECURITY.md)。

- gitleaks pre-commit hook + CI 密碼掃描
- CodeQL (Python + JS) + Bandit + npm audit + Trivy (容器) + Kubescape (manifests) 整合在 CI
- Webhook HMAC 驗證是**強制的**（驗證失敗直接拒絕）
- 變更型端點需要 API key（未設定則回傳 503）
- CORS 嚴格白名單 — 啟動時拒絕 wildcard
- 容器：non-root、唯讀 root FS、drop all caps、seccomp RuntimeDefault、多階段建置
- Kubernetes：Pod Security Standard `restricted` 強制執行、NetworkPolicy 預設拒絕、External Secrets 來自 AWS Secrets Manager、ALB with TLS 1.3
- Dependabot 每週更新 pip / npm / Docker / Actions

## 專案結構

```
dora-metrics-platform/
├── backend/                          FastAPI 服務
│   └── app/
│       ├── api/{routes,security}.py  端點 + 認證輔助
│       ├── collectors/               GitHub + Claude Code 收集器
│       ├── models/                   SQLAlchemy 資料模型
│       ├── services/dora_calculator  DORA 計算邏輯
│       └── main.py                   應用程式 + 排程器
├── frontend/                         React + Vite 儀表板
├── infra/
│   ├── docker/                       安全強化的多階段 Dockerfile + nginx
│   └── k8s/                          EKS manifests (kustomize)
├── otel-collector/                   OpenTelemetry 設定（選配）
├── docs/                             架構 + EKS + 遙測指南
├── .github/                          CI workflows + Dependabot
└── docker-compose.yml                本地開發用 stack
```

## 授權條款

[MIT](LICENSE)
