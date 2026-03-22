### **Agent Newsletter**

A `LangGraph-based agent` that collects newsletters from `Gmail` (unread), classifies and summarizes them, save their embeddings for search on demand, and delivers results via `Telegram`(Two-way).

#### Project layout

```text
Agent_Newsletter/
├── main.py                 # Entry: Telegram webhook server + APScheduler (daily run)
├── agents/
│   ├── state.py            # AgentState / MailItem
│   └── graph.py            # LangGraph definition
├── nodes/
│   └── nodes.py            # Pipeline nodes (ingest, classify, summary, …)
├── config/
│   ├── settings.py         # Environment (.env) via Pydantic Settings
│   └── llm.py              # Vertex AI Gemini Flash/Pro factories
├── db/
│   └── repository.py       # PostgreSQL + pgvector CRUD
├── tools/
│   ├── gmail.py            # Gmail API: fetch unread + mark processed
│   ├── crawler.py          # Article extraction + paywall hint (Redis 24h cache)
│   ├── dedup.py            # Redis deduplication by Message-ID
│   └── telegram.py         # Outbound Telegram messages
├── requirements.txt
├── Dockerfile
└── docker-compose.yml      # PostgreSQL + Redis + agent
```

#### Runtime and dependencies

- **Python** 3.11  
- **Orchestration:** LangGraph (`>=0.2` per requirements)  
- **LLM:** Vertex AI Gemini 2.5 Flash / Pro (model names configurable)  
- **Database:** PostgreSQL 16 + pgvector  
- **Cache:** Redis 7  
- **Bot:** python-telegram-bot (`>=21`)  
- **Scheduler:** APScheduler (`>=3.10,<4.0`)

#### Quick start (local)

1. Prepare `.env` (see [Configuration](#configuration)).

2. Start DB, Redis, and the agent:

```bash
docker compose up --build
```

3. Configure the Telegram webhook: `TELEGRAM_WEBHOOK_URL` must be a publicly reachable HTTPS URL. For local testing, a tunnel (e.g. ngrok) is the usual approach.

#### Configuration

Settings are defined in [config/settings.py](config/settings.py) and loaded from `.env` by default.

#### Gmail: fetch volume

With a once-daily cron schedule, `GMAIL_FETCH_LIMIT` effectively caps how many emails are ingested per run.

- `GMAIL_FETCH_LIMIT` — max messages to ingest per run (default 30)  
- `GMAIL_QUERY` — Gmail search query (default `is:unread (category:updates OR label:newsletters)`)


Implementation: [tools/gmail.py](tools/gmail.py) limits `messages.list` results accordingly.

#### Schedule

- `SCHEDULE_HOUR` (default 6)  
- `SCHEDULE_TIMEZONE` (default Asia/Seoul)

#### Required environment variables (summary)

- **GCP / Vertex:** `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (default `us-central1`), and optionally `GOOGLE_APPLICATION_CREDENTIALS`  
- **Gmail OAuth:** `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`  
- **Telegram:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_URL`  
- **Data stores:** `DATABASE_URL`, `REDIS_URL` (default `redis://localhost:6379/0`)

---

#### Full workflow

![Image](https://github.com/user-attachments/assets/ec94fee7-11e4-4b41-ae0d-10aee42e099d)


#### Data flow summary

| Stage        | Storage / services                          |
|-------------|---------------------------------------------|
| Dedup       | Redis (Message-ID)                        |
| Skip list   | PostgreSQL                                |
| Crawl cache | Redis (URL body cache)                    |
| Summaries   | PostgreSQL + pgvector (embedding + metadata) |
| Delivery    | Telegram Bot API                          |

---

#### TBD lists

- [ ] Sender whitelist / allowed domains to reduce noise and token use  
- [ ] Mark Gmail messages as read only after the pipeline succeeds (avoid loss on mid-run failure)  
- [ ] Optional Gmail query window (e.g. `newer_than:Xd`) for large unread backlogs  
- [ ] Tests for Gmail label/category query combinations  
