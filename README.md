# 🧠 ComplianceAI - Backend

> FastAPI backend powering the AI Regulatory Compliance Agent. Orchestrates a 5-agent LangGraph pipeline that identifies applicable regulations, performs gap analysis, scores risks, generates remediation plans, and produces PDF compliance reports.

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.55-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](LICENSE)

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agent Pipeline](#agent-pipeline)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Tech Stack](#tech-stack)
- [License](#license)

---

## Overview

The backend is the brain of ComplianceAI. It receives company profile data from the React frontend, processes uploaded documents, and runs a **5-node LangGraph pipeline** that sequentially:

1. **Identifies** which government regulations apply to the company
2. **Analyzes gaps** between the company's current state and regulatory requirements
3. **Scores risks** with severity ratings (0–100) for each compliance gap
4. **Generates remediation** action plans with priorities and timelines
5. **Produces a PDF report** and saves all results to PostgreSQL

Real-time progress is streamed to the frontend via **Server-Sent Events (SSE)** through Redis pub/sub.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI Backend (:8000)            │
│                                                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Auth     │  │ Analysis  │  │ SSE Streaming    │  │
│  │ Router   │  │ Router    │  │ Router           │  │
│  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
│       │              │                  │            │
│       ▼              ▼                  ▼            │
│  ┌─────────┐  ┌─────────────┐    ┌──────────┐      │
│  │PostgreSQL│  │ LangGraph   │    │  Redis   │      │
│  │ (Users)  │  │ Pipeline    │    │ (Pub/Sub)│      │
│  └─────────┘  │ (5 Agents)  │    └──────────┘      │
│               └──────┬──────┘                       │
│                      │                              │
│          ┌───────────┼───────────┐                  │
│          ▼           ▼           ▼                  │
│     ┌────────┐  ┌────────┐  ┌────────┐             │
│     │ Gemini │  │ Qdrant │  │DuckDuck│             │
│     │  LLM   │  │  (RAG) │  │Go Search│            │
│     └────────┘  └────────┘  └────────┘             │
└─────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

The pipeline is a **linear StateGraph** — every analysis passes through all 5 nodes sequentially:

```
START → Regulation Identifier → Gap Analysis → Risk Scoring → Remediation → Report Generator → END
```

| Node | Agent | LLM Calls | Uses RAG | Uses Web |
|------|-------|:---------:|:--------:|:--------:|
| 1 | **Regulation Identifier** | 1 | ✅ (broad) | ✅ (external mode only) |
| 2 | **Gap Analysis** | 1 per regulation | ✅ (filtered) | ❌ |
| 3 | **Risk Scoring** | 1 | ❌ | ❌ |
| 4 | **Remediation** | 1 | ✅ (filtered) | ❌ |
| 5 | **Report Generator** | 0 | ❌ | ❌ |

**Total per analysis: ~5–11 Gemini API calls** depending on the number of applicable regulations found.

### Analysis Modes

| Mode | Description | Web Search |
|------|-------------|:----------:|
| `self` | Analyze your own company | ❌ |
| `external` | Analyze another company | ✅ DuckDuckGo |

### Information Availability

| Level | Confidence Tagging | Risk Score Output |
|-------|-------------------|-------------------|
| `full` | `CONFIRMED` | Single score (e.g., 74) |
| `partial` | `PROBABLE` | Range (e.g., 60–85, est. 74) |
| `minimal` | `UNKNOWN` | Wide range (e.g., 40–90, est. 68) |

---

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Login and receive JWT token |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyze` | Submit a company profile for compliance analysis |
| `POST` | `/analyze/upload` | Upload PDF/DOC documents for context |
| `GET` | `/analyze/result/{analysis_id}` | Get analysis results |

### Streaming

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/analysis/stream/{session_id}` | SSE stream for real-time agent progress |

### History & Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/history` | List past analyses |
| `GET` | `/history/{id}` | Get a specific past analysis |
| `GET` | `/reports/{id}/download` | Download PDF compliance report |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check endpoint |

---

## Project Structure

```
backend/
├── Dockerfile                  # Python 3.11-slim + CPU-only PyTorch
├── requirements.txt            # Pinned dependencies
├── LICENSE                     # GPL v2
│
└── app/
    ├── main.py                 # FastAPI app entry point, CORS, router registration
    ├── config.py               # Pydantic Settings (env vars)
    ├── database.py             # SQLAlchemy engine & session
    ├── redis_client.py         # Redis connection & progress helpers
    ├── qdrant_client.py        # Qdrant vector DB connection
    │
    ├── models/                 # SQLAlchemy ORM models
    │   ├── user.py             # Users table
    │   ├── company.py          # Companies table
    │   ├── analysis.py         # Analysis runs table (JSONB outputs)
    │   └── report.py           # Generated reports table (PDF bytes)
    │
    ├── schemas/                # Pydantic request/response schemas
    │   ├── auth.py             # Login/Register schemas
    │   ├── company.py          # Company profile schemas (3 modes)
    │   └── analysis.py         # Analysis response schemas
    │
    ├── agents/                 # LangGraph multi-agent pipeline
    │   ├── state.py            # ComplianceState TypedDict
    │   ├── graph.py            # StateGraph definition & compilation
    │   ├── regulation_identifier.py  # Node 1: Find applicable regulations
    │   ├── gap_analysis.py           # Node 2: Compare vs requirements
    │   ├── risk_scoring.py           # Node 3: Score gap severity
    │   ├── remediation.py            # Node 4: Generate fix plans
    │   └── report_generator.py       # Node 5: Build report & save
    │
    ├── tools/                  # Shared tools used by agents
    │   ├── qdrant_search.py    # RAG retrieval (cosine similarity)
    │   ├── web_search.py       # DuckDuckGo search (external mode)
    │   └── pdf_generator.py    # ReportLab PDF generation
    │
    ├── utils/                  # Authentication utilities
    │   ├── jwt.py              # JWT token creation & validation
    │   └── hashing.py          # bcrypt password hashing
    │
    └── routers/                # API route handlers
        ├── auth.py             # /auth endpoints
        ├── analysis.py         # /analyze endpoints
        ├── upload.py           # /analyze/upload endpoint
        ├── sse.py              # /analysis/stream SSE endpoint
        ├── history.py          # /history endpoints
        └── reports.py          # /reports endpoints
```

---

## Environment Variables

These are loaded via Pydantic Settings from a `.env` file (typically mounted from the `Infrastructure` repo):

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `GROQ_API_KEY` | Groq API key (optional) | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-1.5-flash` |
| `POSTGRES_USER` | PostgreSQL username | — |
| `POSTGRES_PASSWORD` | PostgreSQL password | — |
| `POSTGRES_DB` | PostgreSQL database name | — |
| `POSTGRES_HOST` | PostgreSQL host | `postgres` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `REDIS_HOST` | Redis host | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `QDRANT_HOST` | Qdrant host | `qdrant` |
| `QDRANT_PORT` | Qdrant port | `6333` |
| `QDRANT_COLLECTION` | Qdrant collection name | `regulations` |
| `EMBEDDING_MODEL` | Sentence transformer model | `all-MiniLM-L6-v2` |
| `JWT_SECRET_KEY` | Secret key for JWT signing | — |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_EXPIRE_MINUTES` | JWT token expiry | `1440` |

---

## Local Development

### With Docker (Recommended)

The backend is designed to run as part of the full Docker Compose stack from the [`Infrastructure`](../Infrastructure) repo:

```bash
cd Infrastructure
docker compose up --build backend
```

### Standalone (for development)

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install CPU-only PyTorch first
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies
pip install -r requirements.txt

# Set environment variables (create .env or export)
# ... see Environment Variables section above

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> **Note:** The backend requires PostgreSQL, Redis, and Qdrant to be running. Use Docker Compose for the easiest setup.

---

## Tech Stack

| Category | Technology |
|----------|-----------|
| **Framework** | FastAPI 0.115 |
| **Runtime** | Python 3.11, Uvicorn |
| **LLM** | Google Gemini 2.0 Flash |
| **Agent Framework** | LangGraph 0.2.55 |
| **Embeddings** | `all-MiniLM-L6-v2` (384-dim, CPU) |
| **Database** | PostgreSQL 16 (SQLAlchemy ORM) |
| **Vector DB** | Qdrant (cosine similarity) |
| **Cache** | Redis 7 (session progress, SSE) |
| **Auth** | JWT (python-jose) + bcrypt |
| **PDF** | ReportLab |
| **Validation** | Pydantic v2 |
| **HTTP Client** | httpx (for web search) |

---

## License

This project is licensed under the **GNU General Public License v2** — see the [LICENSE](LICENSE) file for details.
