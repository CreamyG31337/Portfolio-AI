import re

with open("web_dashboard/routes/admin_routes.py", "r") as f:
    code = f.read()

update_search = """        # Trigger rebuild from the earliest affected date
        job_id = None
        try:
            job_id = trigger_background_rebuild(fund, earliest_date)
        except Exception as rb_e:
            logger.error(f"Rebuild trigger error after trade update: {rb_e}")

        # Bump cache version
        bump_cache_version()

        return jsonify({
            "success": True,
            "message": f"Trade {tid} updated: {action} {shares} {ticker}",
            "rebuild_job_id": job_id
        })"""

update_replace = """        # Check if the position was closed by this update
        watchlist_removed = remove_closed_position_from_watchlist(client, fund, ticker)
        old_ticker = old_trade.get('ticker', '').upper()
        if ticker != old_ticker and old_ticker:
            old_watchlist_removed = remove_closed_position_from_watchlist(client, fund, old_ticker)
            watchlist_removed = list(set(watchlist_removed + old_watchlist_removed))

        # Trigger rebuild from the earliest affected date
        job_id = None
        try:
            job_id = trigger_background_rebuild(fund, earliest_date)
        except Exception as rb_e:
            logger.error(f"Rebuild trigger error after trade update: {rb_e}")

        # Bump cache version
        bump_cache_version()

        return jsonify({
            "success": True,
            "message": f"Trade {tid} updated: {action} {shares} {ticker}",
            "rebuild_job_id": job_id,
            "rebuild_reason": "edit" if job_id else None,
            "watchlist_removed": watchlist_removed,
        })"""

code = code.replace(update_search, update_replace)

delete_search = """        # Trigger rebuild from the deleted trade's date
        job_id = None
        try:
            job_id = trigger_background_rebuild(fund, trade_date)
        except Exception as rb_e:
            logger.error(f"Rebuild trigger error after trade delete: {rb_e}")

        # Bump cache version
        bump_cache_version()

        return jsonify({
            "success": True,
            "message": f"Trade {tid} deleted",
            "rebuild_job_id": job_id
        })"""

delete_replace = """        # Check if the position was closed by this deletion
        watchlist_removed = remove_closed_position_from_watchlist(client, fund, old_trade.get('ticker', ''))

        # Trigger rebuild from the deleted trade's date
        job_id = None
        try:
            job_id = trigger_background_rebuild(fund, trade_date)
        except Exception as rb_e:
            logger.error(f"Rebuild trigger error after trade delete: {rb_e}")

        # Bump cache version
        bump_cache_version()

        return jsonify({
            "success": True,
            "message": f"Trade {tid} deleted",
            "rebuild_job_id": job_id,
            "rebuild_reason": "delete" if job_id else None,
            "watchlist_removed": watchlist_removed,
        })"""

code = code.replace(delete_search, delete_replace)

with open("web_dashboard/routes/admin_routes.py", "w") as f:
    f.write(code)


with open("web_dashboard/src/js/trade_entry.ts", "r") as f:
    ts = f.read()

ts = ts.replace("""    rebuild_reason?: 'backdated' | 'sell' | null;""", """    rebuild_reason?: string | null;""")

ts_edit_search = """        if (result.rebuild_job_id) {
            showToastForTradeEntry('Background rebuild started', 'info');
        }
    } catch (error) {"""

ts_edit_replace = """        if (result.rebuild_job_id) {
            const why = result.rebuild_reason || 'edit';
            showToastForTradeEntry(`⏳ Updating positions in the background (${why})`, 'info');
        }
        if (result.watchlist_removed && result.watchlist_removed.length > 0) {
            showToastForTradeEntry(
                `Position closed: removed from the watchlist (${result.watchlist_removed.join(', ')})`,
                'info'
            );
        }
    } catch (error) {"""

ts = ts.replace(ts_edit_search, ts_edit_replace)

with open("web_dashboard/src/js/trade_entry.ts", "w") as f:
    f.write(ts)
