import re

with open('web_dashboard/routes/admin_routes.py', 'r') as f:
    content = f.read()

# _get_portfolio_tickers
search2 = """def _get_portfolio_tickers() -> set:
    \"\"\"Get all distinct tickers currently in the portfolio\"\"\"
    try:
        client = SupabaseClient(use_service_role=True)
        tickers = set()
        offset = 0
        page_size = 1000

        while True:
            result = client.supabase.table("portfolio_positions") \\
                .select("ticker") \\
                .range(offset, offset + page_size - 1) \\
                .execute()

            if not result.data:
                break

            for row in result.data:
                ticker = row.get("ticker")
                if ticker:
                    tickers.add(ticker)

            if len(result.data) < page_size:
                break

            offset += page_size
            if offset > 50000:
                logger.warning("Reached 50,000 row safety limit in _get_portfolio_tickers")
                break

        return tickers
    except Exception as e:
        logger.error(f"Error fetching portfolio tickers: {e}", exc_info=True)
        return set()"""

replace2 = """from supabase_pagination import fetch_all_rows

def _get_portfolio_tickers() -> set:
    \"\"\"Get all distinct tickers currently in the portfolio\"\"\"
    try:
        client = SupabaseClient(use_service_role=True)
        tickers = set()

        rows = fetch_all_rows(client, "portfolio_positions", select="ticker")
        for row in rows:
            ticker = row.get("ticker")
            if ticker:
                tickers.add(ticker)

        return tickers
    except Exception as e:
        logger.error(f"Error fetching portfolio tickers: {e}", exc_info=True)
        return set()"""

content = content.replace(search2, replace2)

with open('web_dashboard/routes/admin_routes.py', 'w') as f:
    f.write(content)
