# Portfolio-AI

**Formerly:** LLM Micro-Cap Trading Bot

**Portfolio-AI** is a comprehensive, AI-driven investment management system that combines a powerful CLI trading engine with a modern, multi-user web dashboard. It leverages Large Language Models (LLMs) for market analysis, automated research, and portfolio optimization, specifically tailored for micro-cap stocks and dual-currency portfolios (USD/CAD).

## 🚀 System Overview

The project consists of three main pillars:

1.  **Core Trading Engine (CLI)**: A Python-based command-line tool for daily trading operations, portfolio management, and generating LLM prompts.
2.  **Web Dashboard (Flask)**: A secure, multi-user web application for real-time portfolio tracking, performance visualization, and admin management.
3.  **AI Research System**: An autonomous background system that hunts for news, generates semantic embeddings, and provides AI-powered market intelligence.

---

## 🖥️ Web Dashboard

The **Web Dashboard** is a modern Flask application backed by Supabase, offering a premium user experience for portfolio tracking.

### Key Features
*   **Secure Multi-User Access**: Professional authentication with Supabase Auth, ensuring users only see their assigned funds.
*   **Real-Time Tracking**: Live updates of portfolio positions, cash balances, and performance metrics.
*   **Advanced UI**: Built with **Tailwind CSS** and **Flowbite** for a responsive, dark-mode-ready interface.
*   **Interactive Charts**: Dynamic Plotly performance graphs with benchmark comparisons (S&P 500, QQQ, etc.).
*   **Admin Tools**: Comprehensive admin interface for managing users, funds, and system logs.

### AI Research Integration 🧠
The dashboard includes a dedicated **AI Assistant** and **Research Hub**:
*   **Automated News Collection**: Background jobs (SearXNG) continuously scour the web for market news, ticker updates, and ETF sector trends.
*   **Semantic Search**: Vector embeddings (via Ollama) allow for natural language searching through thousands of financial articles.
*   **Smart Summaries**: AI-generated summaries of complex financial news, automatically tagged by sector and ticker.

> For detailed Web Dashboard documentation, see [web_dashboard/README.md](web_dashboard/README.md).
> For the AI Research System deep dive, see [web_dashboard/AI_RESEARCH_SYSTEM.md](web_dashboard/AI_RESEARCH_SYSTEM.md).

---

## 🤖 Core Trading Engine (CLI)

The CLI engine is the workhorse for daily operations, allowing for rapid data entry and analysis.

### Features
*   **LLM integration**: Seamless integration with ChatGPT, Claude, and other models for analysis.
*   **Dual Currency Support**: Native handling of CAD and USD cash balances with automatic exchange rate conversion.
*   **Flexible Data Storage**: Switch instantly between **local CSV files** (for development/offline) and **Supabase** (cloud/production) using the Repository Pattern.
*   **Automated Prompt Generation**: Creates comprehensive market analysis prompts to feed into your LLM of choice.

### Quick Start (CLI)
1.  **Install**: `pip install -r requirements.txt`
2.  **Run**: `python run.py`
3.  **Menu**:
    *   `[1]` View Portfolio
    *   `[d]` Generate Daily Trading Prompt
    *   `[b]` / `[s]` Buy/Sell Stocks
    *   `[k]` Cache Management

---

## 📂 Repository Structure

*   **`web_dashboard/`**: The complete Flask web application, Dockerfiles, and frontend assets.
*   **`trading_script.py`**: Main entry point for the CLI trading logic.
*   **`run.py`**: Master launcher script for the CLI tools.
*   **`data/`**: Repository pattern implementations (CSV, Supabase).
*   **`trading_data/`**: Local data storage for CSV mode.
*   **`utils/`**: Shared utility functions.

## 🛠️ Setup & Installation

### Prerequisites
*   Python 3.11+
*   Supabase Account (for Cloud/Web features)
*   Docker (for running the Web Dashboard locally)

### 1. Environment Setup
Clone the repo and set up your virtual environment:
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configuration (`.env`)
Copy the example environment file and configure your keys:
```bash
cp web_dashboard/env.example web_dashboard/.env
```
Key variables include `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `FLASK_SECRET_KEY`.

### 3. Running the Dashboard (Local)
```bash
cd web_dashboard
python app.py
```
Or run with Docker:
```bash
docker-compose up --build
```

### 4. Running the CLI
```bash
python run.py
```

## 🔄 Data Storage Modes

**Portfolio-AI** supports a hybrid data model:
*   **CSV Mode**: Fast, local, offline-capable. Great for testing and rapid development.
*   **Supabase Mode**: Centralized cloud database. Required for the Web Dashboard and multi-user access.
*   **Dual-Write Mode**: Writes to both CSV and Supabase for redundancy.

Switch modes easily via the CLI:
```bash
python simple_repository_switch.py supabase
# or
python simple_repository_switch.py csv
```

## 📚 Documentation Index

**System Architecture & core Concepts**
*   [Repository Pattern & Data Storage](REPOSITORY_PATTERN.md)
*   [Performance Logging](PERFORMANCE_LOGGING.md)
*   [North American Trading Guide](NORTH_AMERICAN_TRADING_GUIDE.md)

**Technical Documentation (in `docs/`)**
*   [Cache Management](docs/CACHE_MANAGEMENT.md)
*   [Database Schema](docs/DATABASE_SCHEMA.md)
*   [Portfolio Architecture](docs/PORTFOLIO_ARCHITECTURE.md)
*   [ETF Watchtower](docs/ETF_WATCHTOWER.md)
*   [Webull Import](docs/WEBULL_IMPORT.md)
*   [Email Ingest](docs/EMAIL_INGEST.md)

**Web Dashboard**
*   [Dashboard Setup & Config](web_dashboard/README.md)
*   [AI Research System](web_dashboard/AI_RESEARCH_SYSTEM.md)
*   [Authentication](web_dashboard/AUTHENTICATION.md)

## 📄 License

This project is open-source. See the LICENSE file for details.
