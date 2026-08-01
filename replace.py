import re

with open('web_dashboard/scheduler/jobs_yahoo_sedi_insiders.py', 'r') as f:
    content = f.read()

new_content = re.sub(
    r"""                for record in rows:
                    try:
                        if _trade_exists\(supabase, record\):
                            skipped_dupes \+= 1
                            continue
                        result = \(
                            supabase.supabase.table\("insider_trades"\)
                            .upsert\(record, on_conflict=_UPSERT_CONFLICT\)
                            .execute\(\)
                        \)
                        if result.data:
                            inserted \+= 1
                    except Exception as row_exc:
                        errors \+= 1
                        logger.warning\(
                            "yahoo_sedi upsert failed %s %s: %s",
                            ticker,
                            record.get\("insider_name"\),
                            row_exc,
                        \)""",
    """                # ⚡ Bolt: Batch upserts instead of per-row to reduce round-trips
                records_to_upsert = []
                for record in rows:
                    if _trade_exists(supabase, record):
                        skipped_dupes += 1
                        continue
                    records_to_upsert.append(record)

                if records_to_upsert:
                    try:
                        result = (
                            supabase.supabase.table("insider_trades")
                            .upsert(records_to_upsert, on_conflict=_UPSERT_CONFLICT)
                            .execute()
                        )
                        if result.data:
                            inserted += len(result.data)
                    except Exception as batch_exc:
                        errors += 1
                        logger.warning(
                            "yahoo_sedi batch upsert failed for %s: %s",
                            ticker,
                            batch_exc,
                        )""",
    content
)

with open('web_dashboard/scheduler/jobs_yahoo_sedi_insiders.py', 'w') as f:
    f.write(new_content)
