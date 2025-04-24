# UBS Compliance Agent System

UBS Compliance Agent System is an AI-powered multi-agent platform for processing global shareholder reporting alerts. It leverages multiple specialized agents to automate and validate compliance workflows for financial securities, focusing on regulated and growth markets in Germany and France.

## Features
- **Multi-Agent System**: Modular agents for market validation, outstanding shares validation, evidence collection, and decision making.
- **Market Type Validation**: Determines if a security is traded on a regulated or growth market using ISIN and country-specific rules.
- **Outstanding Shares Validation**: Compares UBS system data with commercial registers to flag discrepancies.
- **Evidence Collection**: Automated PDF snapshots of relevant web pages for audit trails.
- **REST API**: FastAPI-powered endpoints for alert processing, batch processing, and evidence retrieval.
- **Audit Logging**: All decisions and evidence are logged for compliance and traceability.

## Project Structure
```
├── agents/                # Multi-agent system factory and orchestration
├── data_access/           # Data loaders for alerts
├── evidence/              # Collected evidence PDFs and screenshots
├── main.py                # FastAPI app entrypoint
├── market_validators/     # Market validation logic
├── models/                # Data models for alerts and results
├── results/               # Output results and reports
├── share_validators/      # Outstanding shares validation logic
├── test/                  # Test cases
├── utils/                 # Utility functions (e.g., PDF generation)
```

## Installation
1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd ubs_agent
   ```
2. **Set up environment variables**
   - Copy `.env.example` to `.env` and fill in your OpenAI API key and model.

## Usage
Start the FastAPI server:
```bash
uv run main.py
```

### API Endpoints
- `POST /process_alert` – Process a single alert
- `POST /process_alerts_batch` – Batch process multiple alerts
- `GET /evidence/{alert_id}` – Retrieve evidence for an alert
- `GET /health` – Health check

## Configuration
- **OpenAI API**: Requires `OPENAI_API_KEY` and (optionally) `OPENAI_MODEL` in your `.env` file.
- **Python Version**: 3.10+

## Testing
Run unit tests with pytest:
```bash
pytest
```

## Dependencies
- fastapi
- uvicorn
- pandas
- playwright
- pyautogen
- reportlab
- python-dotenv
- aiohttp
- beautifulsoup4

See `pyproject.toml` for the full list.

## License
Proprietary – For internal UBS use only.

---
*Generated on 2025-04-24*
