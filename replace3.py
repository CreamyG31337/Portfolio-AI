import re

with open('web_dashboard/scheduler/jobs_portfolio.py', 'r') as f:
    content = f.read()

new_content = re.sub(
    r"""                            upsert_result = client.supabase.table\("portfolio_positions"\)\\
                                .upsert\(
                                    updated_positions,
                                    on_conflict="fund,ticker,date_only"
                                \)\\
                                .execute\(\)""",
    """                            # ⚡ Bolt: Execute batched upserts in chunks instead of all at once to avoid timeouts
                            upserted_count = 0
                            chunk_size = 200
                            for i in range(0, len(updated_positions), chunk_size):
                                chunk = updated_positions[i:i + chunk_size]
                                upsert_result = client.supabase.table("portfolio_positions")\\
                                    .upsert(
                                        chunk,
                                        on_conflict="fund,ticker,date_only"
                                    )\\
                                    .execute()
                                if upsert_result.data:
                                    upserted_count += len(upsert_result.data)
                                else:
                                    upserted_count += len(chunk)""",
    content
)

new_content = re.sub(
    r"""                            upserted_count = len\(upsert_result.data\) if upsert_result.data else len\(updated_positions\)
                            total_positions_updated \+= upserted_count""",
    """                            total_positions_updated += upserted_count""",
    new_content
)

with open('web_dashboard/scheduler/jobs_portfolio.py', 'w') as f:
    f.write(new_content)
