"""
Benchmark script for fetch optimization (PRs #149, #152, #159, #163, #171, #175, #187).

Measures wall-clock time for:
1. Ticker list fetch (get_all_unique_tickers)
2. Congress unique filter values (tickers + politicians)
3. Insider unique filter values (tickers + names)

Requires live Supabase connection (set SUPABASE_URL and SUPABASE_KEY env vars).
"""
import sys
import os
import time
import statistics

# Add web_dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))


def benchmark(func, *args, runs=3, label=""):
    """Run a function multiple times and return median wall-clock time."""
    times = []
    result = None
    for i in range(runs):
        start = time.perf_counter()
        result = func(*args)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  Run {i+1}/{runs}: {elapsed:.3f}s")

    median = statistics.median(times)
    count = len(result) if result is not None else 0
    print(f"  ✅ {label}: median={median:.3f}s, items={count}")
    return median, count


def main():
    from supabase_client import SupabaseClient

    print("=" * 60)
    print("Fetch Optimization Benchmark")
    print("=" * 60)

    client = SupabaseClient(use_service_role=True)
    refresh_key = 0

    results = {}

    # 1. Ticker list fetch
    print("\n📊 1. Ticker List Fetch (get_all_unique_tickers)")
    print("-" * 40)
    try:
        from ticker_utils import get_all_unique_tickers
        median, count = benchmark(
            get_all_unique_tickers, client, None,
            runs=3, label="get_all_unique_tickers"
        )
        results["ticker_list_fetch"] = {"median_s": median, "count": count}
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # 2. Congress: unique tickers
    print("\n📊 2. Congress Unique Tickers")
    print("-" * 40)
    try:
        from flask_data_utils import fetch_unique_column_values_parallel
        median, count = benchmark(
            fetch_unique_column_values_parallel,
            client, 'congress_trades_enriched', 'ticker',
            runs=3, label="congress_tickers"
        )
        results["congress_tickers"] = {"median_s": median, "count": count}
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # 3. Congress: unique politicians
    print("\n📊 3. Congress Unique Politicians")
    print("-" * 40)
    try:
        median, count = benchmark(
            fetch_unique_column_values_parallel,
            client, 'congress_trades_enriched', 'politician',
            runs=3, label="congress_politicians"
        )
        results["congress_politicians"] = {"median_s": median, "count": count}
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # 4. Insider: unique tickers
    print("\n📊 4. Insider Unique Tickers")
    print("-" * 40)
    try:
        median, count = benchmark(
            fetch_unique_column_values_parallel,
            client, 'insider_trades', 'ticker',
            runs=3, label="insider_tickers"
        )
        results["insider_tickers"] = {"median_s": median, "count": count}
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # 5. Insider: unique insider names
    print("\n📊 5. Insider Unique Names")
    print("-" * 40)
    try:
        median, count = benchmark(
            fetch_unique_column_values_parallel,
            client, 'insider_trades', 'insider_name',
            runs=3, label="insider_names"
        )
        results["insider_names"] = {"median_s": median, "count": count}
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'Operation':<30} {'Median (s)':<12} {'Items':<8}")
    print("-" * 50)
    for op, data in results.items():
        print(f"{op:<30} {data['median_s']:<12.3f} {data['count']:<8}")

    print("\n✅ Benchmark complete.")
    return results


if __name__ == "__main__":
    main()
