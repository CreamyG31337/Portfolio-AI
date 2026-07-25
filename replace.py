import re

with open('web_dashboard/routes/admin_routes.py', 'r') as f:
    content = f.read()

# _fetch_trade_log_batches
search1 = """def _fetch_trade_log_batches(client, fund: str, batch_size: int = 1000) -> list:
    \"\"\"All non-DRIP trade_log rows for a fund, newest first (paginated Supabase reads).\"\"\"
    rows: list = []
    offset = 0
    while True:
        data_res = (
            client.supabase.table("trade_log")
            .select("*")
            .eq("fund", fund)
            .neq("reason", "DRIP")
            .order("date", desc=True)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        batch = data_res.data or []
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return rows"""

replace1 = """from supabase_pagination import fetch_all_rows

def _fetch_trade_log_batches(client, fund: str, batch_size: int = 1000) -> list:
    \"\"\"All non-DRIP trade_log rows for a fund, newest first (paginated Supabase reads).\"\"\"
    return fetch_all_rows(
        client,
        "trade_log",
        filters=[("fund", "eq", fund), ("reason", "neq", "DRIP")],
        order="date",
        order_desc=True,
        page_size=batch_size
    )"""

content = content.replace(search1, replace1)

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

replace2 = """def _get_portfolio_tickers() -> set:
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

# securities filtering logic
search3 = """        else:  # stock mode - more complex pagination
            # For stock mode, we need to filter out ETF tickers which is harder to paginate
            # Use a larger fetch and filter approach
            query_builder = _build_securities_query(client, query_text).order("ticker")
            page_size = 500
            db_offset = 0
            all_filtered = []

            # Fetch enough to get the requested page
            target_count = offset + limit + 1  # +1 to check if there's more
            while len(all_filtered) < target_count and db_offset < 50000:
                result = query_builder.range(db_offset, db_offset + page_size - 1).execute()
                if not result.data:
                    break
                filtered = [row for row in result.data if row.get("ticker") not in etf_tickers]
                all_filtered.extend(filtered)
                if len(result.data) < page_size:
                    break
                db_offset += page_size

            total = len(all_filtered)  # Approximate - may be more if we hit limit
            has_more = len(all_filtered) > offset + limit
            securities = all_filtered[offset:offset + limit]"""

replace3 = """        else:  # stock mode - more complex pagination
            # For stock mode, we need to filter out ETF tickers which is harder to paginate
            # Use a larger fetch and filter approach

            # Since we can't easily filter by "not in set" at the DB level efficiently via PostgREST
            # and maintain proper count without pulling a lot of data, we use fetch_all_rows for
            # robust filtering.

            def apply_search_query(q):
                if query_text:
                    safe_query = query_text.replace('%', '').replace('_', r'\\_')
                    return q.or_(f"ticker.ilike.%{safe_query}%,company_name.ilike.%{safe_query}%")
                return q

            all_rows = fetch_all_rows(
                client,
                "securities",
                select="ticker, company_name, description",
                order="ticker",
                apply_query=apply_search_query
            )

            all_filtered = [row for row in all_rows if row.get("ticker") not in etf_tickers]

            total = len(all_filtered)
            has_more = len(all_filtered) > offset + limit
            securities = all_filtered[offset:offset + limit]"""

content = content.replace(search3, replace3)

with open('web_dashboard/routes/admin_routes.py', 'w') as f:
    f.write(content)
