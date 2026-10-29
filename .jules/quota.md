## 2025-02-12 - Pagination Gaps in Chunked Supabase Reads
**Bug:** Multiple chunked reads missing `.order()` clauses (e.g., `web_dashboard/outbound_digest_builder.py`, `web_dashboard/admin_utils.py`, `web_dashboard/ticker_analysis_service.py`, `web_dashboard/etf_meta_pipeline.py`) caused skipped or duplicate rows across chunks. `web_dashboard/congress_herd_service.py` and `web_dashboard/insider_clusters_service.py` had non-unique order clauses.
**Learning:** Postgres does not guarantee order between `.range()` pagination queries without an explicit `.order()` clause, leading to inconsistent multi-page reads.
**Prevention:** Always use `fetch_all_rows` from `supabase_pagination` for large reads, and ensure a unique secondary order (like `.order("id")`) when paginating.
