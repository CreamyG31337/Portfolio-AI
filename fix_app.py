import re

with open("web_dashboard/app.py", "r") as f:
    content = f.read()

# Define replacement
search_text = """        # Period filter on first_buy_date
        if period == '2025':
            query = query.gte("first_buy_date", "2025-01-01")
        elif period == 'last_12m':
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            query = query.gte("first_buy_date", cutoff)
        # 'all' = no date filter

        # Status filter (only closed for now)
        query = query.eq("status", "closed")

        # Politician name filter
        if politician:
            # We can't filter on joined table easily, so we'll do it in post-processing
            pass

        # Sorting
        allowed_sorts = {
            'est_pnl': 'est_pnl',
            'pct_return': 'pct_return',
            'est_invested': 'est_invested',
            'days_held': 'days_held',
            'first_buy_date': 'first_buy_date',
            'ticker': 'ticker',
            'spy_pct_change': 'spy_pct_change',
        }
        sort_column = allowed_sorts.get(sort_by, 'est_pnl')
        is_desc = sort_dir.lower() == 'desc'
        query = query.order(sort_column, desc=is_desc, nullsfirst=False)

        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        rows = result.data or []

        # Format response
        positions = []
        for row in rows:
            pol = row.get("politicians") or {}
            pol_name = pol.get("name", "Unknown")

            # Post-filter by politician name if specified
            if politician and politician.lower() not in pol_name.lower():
                continue

            positions.append({
                "id": row.get("id"),
                "politician": pol_name,
                "party": pol.get("party", ""),
                "chamber": pol.get("chamber", ""),
                "ticker": row.get("ticker", ""),
                "buy_count": row.get("buy_count", 0),
                "sell_count": row.get("sell_count", 0),
                "first_buy_date": str(row.get("first_buy_date", ""))[:10],
                "last_sell_date": str(row.get("last_sell_date", ""))[:10],
                "avg_buy_price": float(row["avg_buy_price"]) if row.get("avg_buy_price") else None,
                "avg_sell_price": float(row["avg_sell_price"]) if row.get("avg_sell_price") else None,
                "pct_return": float(row["pct_return"]) if row.get("pct_return") is not None else None,
                "est_invested": float(row["est_invested"]) if row.get("est_invested") else None,
                "est_pnl": float(row["est_pnl"]) if row.get("est_pnl") is not None else None,
                "days_held": row.get("days_held"),
                "spy_pct_change": float(row["spy_pct_change"]) if row.get("spy_pct_change") is not None else None,
            })

        return jsonify({"positions": positions, "total": len(positions)})"""

replace_text = """        # Period filter on first_buy_date
        def _apply_filters(q):
            if period == '2025':
                q = q.gte("first_buy_date", "2025-01-01")
            elif period == 'last_12m':
                from datetime import datetime, timedelta
                cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                q = q.gte("first_buy_date", cutoff)
            # 'all' = no date filter
            # Status filter (only closed for now)
            return q.eq("status", "closed")

        count_query = client.supabase.table("congress_positions").select("id", count="exact", head=True)
        count_query = _apply_filters(count_query)
        count_result = count_query.execute()
        total = count_result.count if count_result.count is not None else 0

        query = _apply_filters(query)

        # Politician name filter
        if politician:
            # We can't filter on joined table easily, so we'll do it in post-processing
            pass

        # Sorting
        allowed_sorts = {
            'est_pnl': 'est_pnl',
            'pct_return': 'pct_return',
            'est_invested': 'est_invested',
            'days_held': 'days_held',
            'first_buy_date': 'first_buy_date',
            'ticker': 'ticker',
            'spy_pct_change': 'spy_pct_change',
        }
        sort_column = allowed_sorts.get(sort_by, 'est_pnl')
        is_desc = sort_dir.lower() == 'desc'
        query = query.order(sort_column, desc=is_desc, nullsfirst=False)

        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        rows = result.data or []

        # Format response
        positions = []
        for row in rows:
            pol = row.get("politicians") or {}
            pol_name = pol.get("name", "Unknown")

            # Post-filter by politician name if specified
            if politician and politician.lower() not in pol_name.lower():
                continue

            positions.append({
                "id": row.get("id"),
                "politician": pol_name,
                "party": pol.get("party", ""),
                "chamber": pol.get("chamber", ""),
                "ticker": row.get("ticker", ""),
                "buy_count": row.get("buy_count", 0),
                "sell_count": row.get("sell_count", 0),
                "first_buy_date": str(row.get("first_buy_date", ""))[:10],
                "last_sell_date": str(row.get("last_sell_date", ""))[:10],
                "avg_buy_price": float(row["avg_buy_price"]) if row.get("avg_buy_price") else None,
                "avg_sell_price": float(row["avg_sell_price"]) if row.get("avg_sell_price") else None,
                "pct_return": float(row["pct_return"]) if row.get("pct_return") is not None else None,
                "est_invested": float(row["est_invested"]) if row.get("est_invested") else None,
                "est_pnl": float(row["est_pnl"]) if row.get("est_pnl") is not None else None,
                "days_held": row.get("days_held"),
                "spy_pct_change": float(row["spy_pct_change"]) if row.get("spy_pct_change") is not None else None,
            })

        # When post-filtering, we'd theoretically adjust total.
        # But this is a Quota correctness fix to stop using len(positions) on truncated pages.
        return jsonify({"positions": positions, "total": total})"""

if search_text not in content:
    print("Could not find search text")

content = content.replace(search_text, replace_text)

with open("web_dashboard/app.py", "w") as f:
    f.write(content)
