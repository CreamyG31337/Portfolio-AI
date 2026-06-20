# Debug Scripts

Command-line utilities for Postgres and dashboard diagnostics. **Not exposed via HTTP.**

## Security

- Run only on the server or dev machine with appropriate credentials
- Admin web features (`/dev/sql`, Admin Logs) require Flask admin auth separately

## Postgres Utilities

```bash
python web_dashboard/debug/postgres_utils.py --test
python web_dashboard/debug/postgres_shell.py
python web_dashboard/debug/verify_postgres_production.py
```

## Portfolio / Performance

Use Flask code paths when debugging charts:

- `portfolio_metrics.py` — NAV / `get_user_investment_metrics()`
- `flask_data_utils.py` — positions, trade log, portfolio over time
- `chart_utils.py` — Plotly figure builders

Run against TEST fund locally:

```bash
cd web_dashboard
python -m pytest tests/test_flask_dashboard_summary.py -v -k performance
```
