import re

with open('web_dashboard/routes/admin_routes.py', 'r') as f:
    content = f.read()

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
                    safe_query = query_text.replace('%', '').replace('_', '\\_')
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
