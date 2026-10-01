import re

with open('web_dashboard/scheduler/jobs_stance_outcomes.py', 'r') as f:
    content = f.read()

pass2_old = """        # Pass 2: score. One price fetch per ticker per run, shared across horizons.
        ticker_cache: dict[str, list[dict[str, Any]]] = {}
        resolved_symbols: dict[str, str] = {}
        skip_reasons: dict[str, int] = {}
        for horizon, candidates in candidates_by_horizon.items():
            for row in candidates:
                ticker = (row.get("ticker") or "").upper()
                try:
                    if ticker not in ticker_cache:
                        ticker_cache[ticker] = _fetch_ticker_closes_resolved(
                            postgres,
                            ticker,
                            min_date - timedelta(days=7),
                            max_date,
                            resolved_symbols,
                        )
                    bench_symbol, bench_rows = _benchmark_for(ticker)
                    result = score_stance_row(
                        row,
                        horizon_days=horizon,
                        now=now,
                        benchmark_rows=bench_rows,
                        ticker_rows=ticker_cache[ticker],
                        benchmark_symbol=bench_symbol,
                    )
                    if result.payload is None:
                        reason = result.skip_reason or "unknown"
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        skipped += 1
                        record_scoring_attempt(
                            postgres,
                            stance_id=row["id"],
                            horizon_days=horizon,
                            reason=reason,
                        )
                        continue
                    payload = result.payload
                    from microcap_cost_model import (
                        belief_from_excess_after_cost,
                        excess_after_cost,
                        round_trip_cost_bps,
                    )

                    meta = sec_meta.get(ticker) or {}
                    # No dollar-ADV column exists on `securities`, so market cap is
                    # the only liquidity proxy available. When it is missing,
                    # round_trip_cost_bps returns None and the row is stored without
                    # an after-cost verdict rather than being haircut at the harshest
                    # 300bps bucket -- a missing reference row must not manufacture a
                    # refutation. The UPSERT below fills the verdict in on a later run
                    # once market cap lands.
                    cost_bps = round_trip_cost_bps(market_cap=meta.get("market_cap"))
                    if cost_bps is None:
                        cost_unknown += 1
                    eac = excess_after_cost(
                        payload["excess_return"],
                        cost_bps,
                        stance=str(payload.get("stance") or ""),
                    )
                    belief = belief_from_excess_after_cost(
                        excess_after_cost_pct=eac,
                        stance=str(payload.get("stance") or ""),
                    )
                    try:
                        postgres.execute_update(
                            \"\"\"
                            -- Price/return columns are immutable scored outcomes and
                            -- are never overwritten. Only the cost verdict is filled
                            -- in, and only when the stored row has none: without this
                            -- a row scored while market cap was missing would keep a
                            -- NULL (or, before this fix, a wrongly-refuted) verdict
                            -- permanently, since the job never revisits it.
                            INSERT INTO stance_outcomes (
                                stance_id, horizon_days, baseline_price, end_price,
                                ticker_return, benchmark_return, excess_return,
                                benchmark_symbol, scoring_version,
                                cost_bps, excess_after_cost, belief_status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (stance_id, horizon_days) DO UPDATE SET
                                cost_bps = EXCLUDED.cost_bps,
                                excess_after_cost = EXCLUDED.excess_after_cost,
                                belief_status = EXCLUDED.belief_status
                            WHERE stance_outcomes.cost_bps IS NULL
                              AND EXCLUDED.cost_bps IS NOT NULL
                            \"\"\",
                            (
                                str(payload["stance_id"]),
                                payload["horizon_days"],
                                payload["baseline_price"],
                                payload["end_price"],
                                payload["ticker_return"],
                                payload["benchmark_return"],
                                payload["excess_return"],
                                payload["benchmark_symbol"],
                                SCORING_VERSION,
                                cost_bps,
                                eac,
                                belief,
                            ),
                        )
                    except Exception as insert_exc:
                        # Pre-migration DBs: fall back to columns without cost fields.
                        if "cost_bps" in str(insert_exc) or "excess_after_cost" in str(insert_exc):
                            postgres.execute_update(
                                \"\"\"
                                INSERT INTO stance_outcomes (
                                    stance_id, horizon_days, baseline_price, end_price,
                                    ticker_return, benchmark_return, excess_return,
                                    benchmark_symbol, scoring_version
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (stance_id, horizon_days) DO NOTHING
                                \"\"\",
                                (
                                    str(payload["stance_id"]),
                                    payload["horizon_days"],
                                    payload["baseline_price"],
                                    payload["end_price"],
                                    payload["ticker_return"],
                                    payload["benchmark_return"],
                                    payload["excess_return"],
                                    payload["benchmark_symbol"],
                                    SCORING_VERSION,
                                ),
                            )
                        else:
                            raise
                    scored += 1
                except Exception as row_exc:
                    errors += 1
                    logger.warning("Failed scoring %s horizon=%s: %s", ticker, horizon, row_exc)"""

pass2_new = """        # Pass 2: score. One price fetch per ticker per run, shared across horizons.
        ticker_cache: dict[str, list[dict[str, Any]]] = {}
        resolved_symbols: dict[str, str] = {}
        skip_reasons: dict[str, int] = {}

        # Accumulators for batch inserts
        outcome_batch = []
        fallback_outcome_batch = []
        attempts_batch = []

        for horizon, candidates in candidates_by_horizon.items():
            for row in candidates:
                ticker = (row.get("ticker") or "").upper()
                try:
                    if ticker not in ticker_cache:
                        ticker_cache[ticker] = _fetch_ticker_closes_resolved(
                            postgres,
                            ticker,
                            min_date - timedelta(days=7),
                            max_date,
                            resolved_symbols,
                        )
                    bench_symbol, bench_rows = _benchmark_for(ticker)
                    result = score_stance_row(
                        row,
                        horizon_days=horizon,
                        now=now,
                        benchmark_rows=bench_rows,
                        ticker_rows=ticker_cache[ticker],
                        benchmark_symbol=bench_symbol,
                    )
                    if result.payload is None:
                        reason = result.skip_reason or "unknown"
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        skipped += 1
                        attempts_batch.append((row["id"], horizon, reason))
                        continue
                    payload = result.payload
                    from microcap_cost_model import (
                        belief_from_excess_after_cost,
                        excess_after_cost,
                        round_trip_cost_bps,
                    )

                    meta = sec_meta.get(ticker) or {}
                    # No dollar-ADV column exists on `securities`, so market cap is
                    # the only liquidity proxy available. When it is missing,
                    # round_trip_cost_bps returns None and the row is stored without
                    # an after-cost verdict rather than being haircut at the harshest
                    # 300bps bucket -- a missing reference row must not manufacture a
                    # refutation. The UPSERT below fills the verdict in on a later run
                    # once market cap lands.
                    cost_bps = round_trip_cost_bps(market_cap=meta.get("market_cap"))
                    if cost_bps is None:
                        cost_unknown += 1
                    eac = excess_after_cost(
                        payload["excess_return"],
                        cost_bps,
                        stance=str(payload.get("stance") or ""),
                    )
                    belief = belief_from_excess_after_cost(
                        excess_after_cost_pct=eac,
                        stance=str(payload.get("stance") or ""),
                    )

                    outcome_batch.append((
                        str(payload["stance_id"]),
                        payload["horizon_days"],
                        payload["baseline_price"],
                        payload["end_price"],
                        payload["ticker_return"],
                        payload["benchmark_return"],
                        payload["excess_return"],
                        payload["benchmark_symbol"],
                        SCORING_VERSION,
                        cost_bps,
                        eac,
                        belief,
                    ))

                    fallback_outcome_batch.append((
                        str(payload["stance_id"]),
                        payload["horizon_days"],
                        payload["baseline_price"],
                        payload["end_price"],
                        payload["ticker_return"],
                        payload["benchmark_return"],
                        payload["excess_return"],
                        payload["benchmark_symbol"],
                        SCORING_VERSION,
                    ))
                    scored += 1
                except Exception as row_exc:
                    errors += 1
                    logger.warning("Failed scoring %s horizon=%s: %s", ticker, horizon, row_exc)

        # Flush attempts
        if attempts_batch:
            record_scoring_attempts(postgres, attempts_batch)

        # Flush outcomes
        if outcome_batch:
            try:
                postgres.execute_many(
                    \"\"\"
                    -- Price/return columns are immutable scored outcomes and
                    -- are never overwritten. Only the cost verdict is filled
                    -- in, and only when the stored row has none: without this
                    -- a row scored while market cap was missing would keep a
                    -- NULL (or, before this fix, a wrongly-refuted) verdict
                    -- permanently, since the job never revisits it.
                    INSERT INTO stance_outcomes (
                        stance_id, horizon_days, baseline_price, end_price,
                        ticker_return, benchmark_return, excess_return,
                        benchmark_symbol, scoring_version,
                        cost_bps, excess_after_cost, belief_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stance_id, horizon_days) DO UPDATE SET
                        cost_bps = EXCLUDED.cost_bps,
                        excess_after_cost = EXCLUDED.excess_after_cost,
                        belief_status = EXCLUDED.belief_status
                    WHERE stance_outcomes.cost_bps IS NULL
                      AND EXCLUDED.cost_bps IS NOT NULL
                    \"\"\",
                    outcome_batch,
                )
            except Exception as insert_exc:
                if "cost_bps" in str(insert_exc) or "excess_after_cost" in str(insert_exc):
                    postgres.execute_many(
                        \"\"\"
                        INSERT INTO stance_outcomes (
                            stance_id, horizon_days, baseline_price, end_price,
                            ticker_return, benchmark_return, excess_return,
                            benchmark_symbol, scoring_version
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (stance_id, horizon_days) DO NOTHING
                        \"\"\",
                        fallback_outcome_batch,
                    )
                else:
                    raise"""

content = content.replace(pass2_old, pass2_new)
with open('web_dashboard/scheduler/jobs_stance_outcomes.py', 'w') as f:
    f.write(content)
