import concurrent.futures
import logging
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

def get_unique_values_parallel(
    client,
    table: str,
    column: str,
    process_func: Callable[[Any], Any] | None = None,
    batch_size: int = 1000,
    max_workers: int = 5,
    limit_rows: int = 100000
) -> list[Any]:
    """
    Fetch unique values from a Supabase table using parallel requests.

    Optimized for performance by fetching concurrent chunks up to a safety limit.
    This avoids slow COUNT(*) queries and maximizes throughput.

    Args:
        client: Supabase client instance
        table: Table name (e.g. 'congress_trades_enriched')
        column: Column name to fetch (e.g. 'ticker')
        process_func: Optional function to process/normalize each value
                      (e.g. normalize_insider_name)
        batch_size: Number of rows to fetch per request (default: 1000)
                    Note: Supabase API limit is typically 1000.
        max_workers: Number of parallel threads (default: 5)
        limit_rows: Maximum total rows to scan (safety limit, default: 100k)

    Returns:
        Sorted list of unique values
    """
    try:
        if client is None:
            return []

        # Optimization: We intentionally avoid COUNT(*) here as it can be slow
        # on large tables (O(N)). Instead, we blindly schedule tasks up to
        # limit_rows. Supabase handles out-of-range requests efficiently
        # (returns empty list), so the overhead of extra requests is minimal
        # compared to the cost of counting or serial fetching.

        unique_values = set()

        def fetch_batch(start, end):
            try:
                # Use range for pagination
                # Note: We assume default ordering is stable enough for snapshots.
                res = client.supabase.table(table)\
                    .select(column)\
                    .range(start, end)\
                    .execute()

                return [item.get(column) for item in res.data if item.get(column)]
            except Exception as e:
                logger.warning(f"Error fetching batch {start}-{end} from {table}: {e}")
                return []

        # Generate tasks
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for start in range(0, limit_rows, batch_size):
                end = start + batch_size - 1
                futures.append(executor.submit(fetch_batch, start, end))

            for future in concurrent.futures.as_completed(futures):
                try:
                    batch_values = future.result()
                    # Stop early if we hit the end?
                    # Ideally yes, but with ThreadPoolExecutor tasks are already scheduled.
                    # Empty results are fast to process.

                    if not batch_values:
                        continue

                    if process_func:
                        for val in batch_values:
                            processed = process_func(val)
                            if processed:
                                unique_values.add(processed)
                    else:
                        unique_values.update(batch_values)
                except Exception as e:
                    logger.error(f"Error processing batch result: {e}")

        return sorted(unique_values)

    except Exception as e:
        logger.error(f"Error in get_unique_values_parallel for {table}.{column}: {e}", exc_info=True)
        return []
