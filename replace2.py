import re

with open('web_dashboard/scheduler/jobs_signals.py', 'r') as f:
    content = f.read()

new_content = re.sub(
    r"""                # Insert or update signal analysis
                try:
                    supabase_client.supabase.table\("signal_analysis"\).upsert\(\{
                        'ticker': ticker.upper\(\),
                        'analysis_date': analysis_date.isoformat\(\),
                        'structure_signal': signals.get\('structure', \{\}\),
                        'timing_signal': signals.get\('timing', \{\}\),
                        'fear_risk_signal': signals.get\('fear_risk', \{\}\),
                        'momentum_signal': signals.get\('momentum', \{\}\),
                        'fundamental_signal': signals.get\('fundamental', \{\}\),
                        'overall_signal': signals.get\('overall_signal', 'HOLD'\),
                        'confidence_score': signals.get\('confidence', 0.0\),
                        'explanation': explanation
                    \}, on_conflict='ticker,analysis_date'\).execute\(\)

                    processed \+= 1

                    if should_alert:
                        alerts_sent \+= 1
                        logger.info\(f"⚠️  Alert: \{ticker\} - \{signals.get\('overall_signal'\)\} signal \(confidence: \{signals.get\('confidence', 0\):.2f\}\)"\)

                    # Store ticker state snapshot \(best-effort\)
                    if ticker_state:
                        try:
                            from web_dashboard.ticker_state import summarize_ticker_state
                            summary = summarize_ticker_state\(ticker_state\)
                            supabase_client.supabase.table\("ticker_state_snapshots"\).upsert\(\{
                                'ticker': ticker.upper\(\),
                                'snapshot_date': analysis_date.isoformat\(\),
                                'state': ticker_state,
                                'summary': summary,
                            \}, on_conflict='ticker,snapshot_date'\).execute\(\)
                        except Exception as snap_err:
                            logger.debug\(f"Failed to store state snapshot for \{ticker\}: \{snap_err\}"\)

                    # Small delay to avoid rate limiting
                    time.sleep\(0.5\)

                except Exception as db_error:
                    logger.error\(f"Error storing signals for \{ticker\}: \{db_error\}"\)
                    errors \+= 1
                    continue""",
    """                # Accumulate for batched upsert
                signal_analyses_to_upsert.append({
                    'ticker': ticker.upper(),
                    'analysis_date': analysis_date.isoformat(),
                    'structure_signal': signals.get('structure', {}),
                    'timing_signal': signals.get('timing', {}),
                    'fear_risk_signal': signals.get('fear_risk', {}),
                    'momentum_signal': signals.get('momentum', {}),
                    'fundamental_signal': signals.get('fundamental', {}),
                    'overall_signal': signals.get('overall_signal', 'HOLD'),
                    'confidence_score': signals.get('confidence', 0.0),
                    'explanation': explanation
                })

                if should_alert:
                    alerts_sent += 1
                    logger.info(f"⚠️  Alert: {ticker} - {signals.get('overall_signal')} signal (confidence: {signals.get('confidence', 0):.2f})")

                if ticker_state:
                    try:
                        from web_dashboard.ticker_state import summarize_ticker_state
                        summary = summarize_ticker_state(ticker_state)
                        ticker_states_to_upsert.append({
                            'ticker': ticker.upper(),
                            'snapshot_date': analysis_date.isoformat(),
                            'state': ticker_state,
                            'summary': summary,
                        })
                    except Exception as snap_err:
                        logger.debug(f"Failed to build state snapshot for {ticker}: {snap_err}")

                processed += 1

                # Small delay to avoid rate limiting data fetcher
                time.sleep(0.5)""",
    content
)

new_content = re.sub(
    r"""        # Process each ticker
        for ticker_data in watchlist:""",
    """        # Process each ticker
        signal_analyses_to_upsert = []
        ticker_states_to_upsert = []

        for ticker_data in watchlist:""",
    new_content
)

new_content = re.sub(
    r"""        duration_ms = int\(\(time.time\(\) - start_time\) \* 1000\)
        message = f"Processed \{processed\} tickers, \{errors\} errors, \{alerts_sent\} alerts, \{ai_explanations\} AI notes"

        try:
            log_job_execution\(job_id, True, message, duration_ms\)""",
    """        # ⚡ Bolt: Execute batched upserts to avoid per-row network roundtrips
        if signal_analyses_to_upsert:
            try:
                # Upsert in chunks to avoid URL size limits if list is huge
                chunk_size = 200
                for i in range(0, len(signal_analyses_to_upsert), chunk_size):
                    chunk = signal_analyses_to_upsert[i:i + chunk_size]
                    supabase_client.supabase.table("signal_analysis").upsert(
                        chunk, on_conflict='ticker,analysis_date'
                    ).execute()
            except Exception as e:
                logger.error(f"Failed to batch insert signal_analysis: {e}")
                errors += 1

        if ticker_states_to_upsert:
            try:
                chunk_size = 200
                for i in range(0, len(ticker_states_to_upsert), chunk_size):
                    chunk = ticker_states_to_upsert[i:i + chunk_size]
                    supabase_client.supabase.table("ticker_state_snapshots").upsert(
                        chunk, on_conflict='ticker,snapshot_date'
                    ).execute()
            except Exception as e:
                logger.error(f"Failed to batch insert ticker_state_snapshots: {e}")
                errors += 1

        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {processed} tickers, {errors} errors, {alerts_sent} alerts, {ai_explanations} AI notes"

        try:
            log_job_execution(job_id, True, message, duration_ms)""",
    new_content
)

with open('web_dashboard/scheduler/jobs_signals.py', 'w') as f:
    f.write(new_content)
