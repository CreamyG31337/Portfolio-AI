"""Fundamentals refresh job: ETF-holding candidates from the Research DB.

Covers: watchlist gaps processed before ETF holdings, the per-run cap, the
holding-ticker regex filter, insert-for-missing-row only for ETF holdings and
only when yfinance reports quoteType == EQUITY, the Research DB failure
fallback to watchlist-only, and the fundamentals_fetch_skips backoff table
(suppression before the cap, per-reason recording, success clearing the row,
growing retry_after, transient exceptions not recorded, skips-table failures
tolerated).
"""

from datetime import datetime, timedelta, timezone

from unittest.mock import MagicMock, patch

from web_dashboard.scheduler import jobs_signals

# Mirrors _FUNDAMENTAL_INDICATOR_COLS in jobs_signals (columns checked to
# decide whether a securities row already has fundamentals).
_INDICATOR_COLS = [
    'forward_pe', 'price_to_book', 'return_on_equity', 'net_margin',
    'revenue_growth', 'current_ratio', 'debt_to_equity',
]


def _sec_row(ticker: str, has_fundamentals: bool = False) -> dict:
    row = {'ticker': ticker, **{col: None for col in _INDICATOR_COLS}}
    if has_fundamentals:
        row['forward_pe'] = 11.0
    return row


def _holding(etf: str, ticker: str, name: str, weight: float) -> dict:
    return {
        'etf_ticker': etf,
        'holding_ticker': ticker,
        'holding_name': name,
        'weight_percent': weight,
    }


class FakeSecuritiesTable:
    """Fake supabase `.table("securities")` supporting select/update/upsert."""

    def __init__(self, rows):
        self.rows = {r['ticker']: r for r in rows}
        self.updates = []  # list of (ticker, payload)
        self.upserts = []  # list of payload dicts
        self._chunk = None
        self._pending_update = None
        self._pending_update_ticker = None
        self._pending_upsert = None

    def select(self, _cols):
        return self

    def in_(self, _col, chunk):
        self._chunk = list(chunk)
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def eq(self, _col, ticker):
        self._pending_update_ticker = ticker
        return self

    def upsert(self, payload):
        self._pending_upsert = payload
        return self

    def execute(self):
        if self._chunk is not None:
            chunk, self._chunk = self._chunk, None
            return MagicMock(data=[self.rows[t] for t in chunk if t in self.rows])
        if self._pending_update is not None:
            self.updates.append((self._pending_update_ticker, self._pending_update))
            self._pending_update = None
            return MagicMock(data=[])
        if self._pending_upsert is not None:
            self.upserts.append(self._pending_upsert)
            self._pending_upsert = None
            return MagicMock(data=[])
        return MagicMock(data=[])


class FakeSkipsTable:
    """Fake supabase `.table("fundamentals_fetch_skips")` supporting the
    select/in_ read and batched upsert/delete writes the job uses."""

    def __init__(self, rows=None, error=None):
        self.rows = {r['ticker']: dict(r) for r in (rows or [])}
        self.error = error
        self.upserts = []  # list of payload batches (each a list of dicts)
        self.deletes = []  # list of ticker chunks
        self._chunk = None
        self._pending_upsert = None
        self._deleting = False

    def select(self, _cols):
        return self

    def in_(self, _col, chunk):
        if self._deleting:
            self.deletes.append(list(chunk))
        else:
            if self.error:
                raise self.error
            self._chunk = list(chunk)
        return self

    def upsert(self, payload):
        self._pending_upsert = payload
        return self

    def delete(self):
        self._deleting = True
        return self

    def execute(self):
        if self._chunk is not None:
            chunk, self._chunk = self._chunk, None
            return MagicMock(data=[self.rows[t] for t in chunk if t in self.rows])
        if self._pending_upsert is not None:
            self.upserts.append(self._pending_upsert)
            self._pending_upsert = None
        return MagicMock(data=[])


class JobResult:
    def __init__(self, table, skips, ticker_mock, log_mock, completed_mock, failed_mock, message):
        self.table = table
        self.skips = skips
        self.ticker_calls = [c.args[0] for c in ticker_mock.call_args_list]
        self.log = log_mock
        self.completed = completed_mock
        self.failed = failed_mock
        self.message = message


def run_refresh_job(
    watchlist_rows,
    securities_rows,
    holdings_rows=None,
    pg_error=None,
    yf_infos=None,
    max_per_run=None,
    skips_rows=None,
    skips_error=None,
    yf_raise=None,
):
    table = FakeSecuritiesTable(securities_rows)
    skips = FakeSkipsTable(rows=skips_rows, error=skips_error)

    def route(name):
        if name == 'securities':
            return table
        if name == 'fundamentals_fetch_skips':
            return skips
        return MagicMock()

    sb = MagicMock()
    sb.supabase.table.side_effect = route

    pg_instance = MagicMock()
    if pg_error is not None:
        pg_instance.execute_query.side_effect = pg_error
    else:
        pg_instance.execute_query.return_value = holdings_rows or []

    yf_infos = yf_infos or {}
    yf_raise = yf_raise or set()

    def make_ticker(t):
        if t in yf_raise:
            raise RuntimeError(f"yfinance blew up for {t}")
        return MagicMock(info=yf_infos.get(t, {}))

    ticker_mock = MagicMock(side_effect=make_ticker)

    with patch('supabase_client.SupabaseClient', return_value=sb), \
         patch('postgres_client.PostgresClient', return_value=pg_instance), \
         patch('yfinance.Ticker', new=ticker_mock), \
         patch.object(jobs_signals, 'get_active_watchlist_rows', return_value=watchlist_rows), \
         patch.object(jobs_signals, 'log_job_execution') as log_mock, \
         patch('utils.job_tracking.mark_job_started'), \
         patch('utils.job_tracking.mark_job_completed') as completed_mock, \
         patch('utils.job_tracking.mark_job_failed') as failed_mock, \
         patch('time.sleep'), \
         patch.object(
             jobs_signals, '_FUNDAMENTALS_MAX_PER_RUN', max_per_run or 400
         ):
        jobs_signals.fundamentals_refresh_job()

    message = ''
    if completed_mock.call_args:
        message = completed_mock.call_args.kwargs.get('message', '')
    return JobResult(table, skips, ticker_mock, log_mock, completed_mock, failed_mock, message)


def test_watchlist_gaps_processed_before_etf_holdings():
    """Watchlist gap first, then ETF holdings ordered by weight; a missing-row
    ETF holding gets inserted, an existing-row gap gets updated."""
    holdings = [
        _holding('BUZZ', 'LIGHT', 'Light Weight Co', 1.0),
        _holding('BUZZ', 'HEAVY', 'Heavy Weight Co', 5.0),
    ]
    securities = [
        _sec_row('WL1'),
        _sec_row('WLDONE', has_fundamentals=True),
        _sec_row('LIGHT'),
    ]
    infos = {
        'WL1': {'quoteType': 'EQUITY', 'forwardPE': 12.0},
        'HEAVY': {'quoteType': 'EQUITY', 'forwardPE': 20.0, 'longName': 'Heavy Weight Co'},
        'LIGHT': {'quoteType': 'EQUITY', 'priceToBook': 3.0},
    }

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}, {'ticker': 'WLDONE'}],
        securities_rows=securities,
        holdings_rows=holdings,
        yf_infos=infos,
    )

    # Watchlist first, then ETF holdings by weight desc
    assert res.ticker_calls == ['WL1', 'HEAVY', 'LIGHT']
    # WL1 (watchlist) and LIGHT (existing row) updated, not inserted
    assert [t for t, _ in res.table.updates] == ['WL1', 'LIGHT']
    # HEAVY has no securities row -> upsert with company name + fundamentals
    assert len(res.table.upserts) == 1
    upsert = res.table.upserts[0]
    assert upsert['ticker'] == 'HEAVY'
    assert upsert['company_name'] == 'Heavy Weight Co'
    assert upsert['forward_pe'] == 20.0
    # Job succeeded with per-source counts in the message
    assert res.failed.assert_not_called() is None
    assert res.log.call_args.args[1] is True
    assert 'watchlist 1 updated' in res.message
    assert 'ETF holdings 1 updated, 1 inserted' in res.message
    assert '0 deferred' in res.message


def test_per_run_cap_defers_remaining_gaps():
    """Only _FUNDAMENTALS_MAX_PER_RUN yfinance calls happen per run; the rest
    is deferred and reported."""
    holdings = [
        _holding('BUZZ', 'HEAVY', 'Heavy Co', 5.0),
        _holding('BUZZ', 'LIGHT', 'Light Co', 1.0),
    ]
    securities = [_sec_row('WL1'), _sec_row('HEAVY'), _sec_row('LIGHT')]
    infos = {
        'WL1': {'quoteType': 'EQUITY', 'forwardPE': 12.0},
        'HEAVY': {'quoteType': 'EQUITY', 'forwardPE': 20.0},
        'LIGHT': {'quoteType': 'EQUITY', 'forwardPE': 30.0},
    }

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        holdings_rows=holdings,
        yf_infos=infos,
        max_per_run=1,
    )

    # Watchlist goes first and consumes the whole cap
    assert res.ticker_calls == ['WL1']
    assert res.table.upserts == []
    assert '2 deferred by per-run cap' in res.message


def test_etf_holding_ticker_regex_filtering():
    """Cash rows and foreign codes are filtered out; dotted US tickers pass."""
    holdings = [
        _holding('IWM', '7203 JP', 'Toyota Motor', 9.0),
        _holding('IWM', '$CASH', 'Cash', 8.0),
        _holding('IWM', 'usd', 'US Dollar', 7.0),
        _holding('IWM', 'BRK.B', 'Berkshire Hathaway', 5.0),
    ]
    securities = [_sec_row('BRK.B')]
    infos = {'BRK.B': {'quoteType': 'EQUITY', 'forwardPE': 15.0}}

    res = run_refresh_job(
        watchlist_rows=[],
        securities_rows=securities,
        holdings_rows=holdings,
        yf_infos=infos,
    )

    assert res.ticker_calls == ['BRK.B']
    assert [t for t, _ in res.table.updates] == ['BRK.B']
    assert res.table.upserts == []


def test_insert_for_missing_row_only_for_etf_holdings_and_only_equity():
    """A watchlist ticker with no securities row stays skipped (never fetched,
    never inserted); ETF holdings are inserted only when quoteType == EQUITY."""
    holdings = [
        _holding('BUZZ', 'HEETF', 'Some Fund', 5.0),
        _holding('BUZZ', 'HEEQ', 'Real Equity Inc', 4.0),
    ]
    infos = {
        'WLNEW': {'quoteType': 'EQUITY', 'forwardPE': 9.0},
        'HEETF': {'quoteType': 'ETF', 'forwardPE': 8.0},
        'HEEQ': {'quoteType': 'EQUITY', 'shortName': 'Real Equity Inc', 'priceToBook': 2.0},
    }

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WLNEW'}],
        securities_rows=[],  # WLNEW, HEETF and HEEQ all have no securities row
        holdings_rows=holdings,
        yf_infos=infos,
    )

    # WLNEW (watchlist, missing row) is never fetched or inserted
    assert 'WLNEW' not in res.ticker_calls
    assert res.ticker_calls == ['HEETF', 'HEEQ']  # weight desc
    # Only the EQUITY holding is inserted
    assert len(res.table.upserts) == 1
    assert res.table.upserts[0]['ticker'] == 'HEEQ'
    assert res.table.upserts[0]['company_name'] == 'Real Equity Inc'
    assert res.table.upserts[0]['price_to_book'] == 2.0
    # The ETF-type holding was skipped, nothing updated
    assert res.table.updates == []
    assert 'ETF holdings 0 updated, 1 inserted, 1 skipped' in res.message


def test_postgres_failure_falls_back_to_watchlist_only():
    """A Research DB outage downgrades to watchlist-only instead of failing."""
    securities = [_sec_row('WL1')]
    infos = {'WL1': {'quoteType': 'EQUITY', 'forwardPE': 10.0}}

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        pg_error=RuntimeError('research db down'),
        yf_infos=infos,
    )

    assert res.ticker_calls == ['WL1']
    assert [t for t, _ in res.table.updates] == ['WL1']
    assert 'watchlist 1 updated' in res.message
    assert 'ETF holdings 0 updated, 0 inserted, 0 skipped, 0 errors' in res.message
    assert res.failed.assert_not_called() is None
    assert res.log.call_args.args[1] is True


# --- fundamentals_fetch_skips backoff ---

def _skip_row(
    ticker: str,
    failure_count: int = 1,
    retry_in_days: float = 30.0,
    reason: str = 'no_fundamentals',
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        'ticker': ticker,
        'reason': reason,
        'failure_count': failure_count,
        'first_failed_at': (now - timedelta(days=365)).isoformat(),
        'retry_after': (now + timedelta(days=retry_in_days)).isoformat(),
    }


def _flattened_upserts(skips) -> dict[str, dict]:
    """{ticker: payload} across all upsert batches."""
    return {row['ticker']: row for batch in skips.upserts for row in batch}


def test_fetch_skip_retry_after_backoff_helper():
    """retry_after = now + 7d * 2**(failure_count-1), capped at 90 days."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert jobs_signals._fetch_skip_retry_after(1, now) == now + timedelta(days=7)
    assert jobs_signals._fetch_skip_retry_after(2, now) == now + timedelta(days=14)
    assert jobs_signals._fetch_skip_retry_after(3, now) == now + timedelta(days=28)
    assert jobs_signals._fetch_skip_retry_after(5, now) == now + timedelta(days=90)
    assert jobs_signals._fetch_skip_retry_after(9, now) == now + timedelta(days=90)
    # Pseudo-sane counts don't blow up
    assert jobs_signals._fetch_skip_retry_after(0, now) == now + timedelta(days=7)


def test_suppressed_tickers_excluded_before_cap():
    """Tickers with an unexpired retry_after are dropped from the work list
    before the per-run cap, so they neither get fetched nor eat the budget."""
    holdings = [
        _holding('BUZZ', 'GONE1', 'Skipped Co 1', 9.0),
        _holding('BUZZ', 'GONE2', 'Skipped Co 2', 8.0),
        _holding('BUZZ', 'ALIVE', 'Alive Co', 7.0),
    ]
    securities = [_sec_row('GONE1'), _sec_row('GONE2'), _sec_row('ALIVE')]
    infos = {
        'GONE1': {'quoteType': 'EQUITY', 'forwardPE': 10.0},
        'GONE2': {'quoteType': 'EQUITY', 'forwardPE': 11.0},
        'ALIVE': {'quoteType': 'EQUITY', 'forwardPE': 12.0},
    }
    skips = [
        _skip_row('GONE1', failure_count=1, retry_in_days=5),
        _skip_row('GONE2', failure_count=2, retry_in_days=13),
    ]

    res = run_refresh_job(
        watchlist_rows=[],
        securities_rows=securities,
        holdings_rows=holdings,
        yf_infos=infos,
        skips_rows=skips,
        max_per_run=1,  # ALIVE still fits: suppressed tickers don't eat budget
    )

    assert res.ticker_calls == ['ALIVE']
    assert [t for t, _ in res.table.updates] == ['ALIVE']
    assert res.skips.upserts == []
    assert res.skips.deletes == []
    assert '2 suppressed by backoff' in res.message
    assert '0 deferred by per-run cap' in res.message


def test_expired_retry_after_is_fetched_again():
    """A skips row whose retry_after has passed no longer suppresses."""
    securities = [_sec_row('WL1')]
    infos = {'WL1': {'quoteType': 'EQUITY', 'forwardPE': 10.0}}

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        yf_infos=infos,
        skips_rows=[_skip_row('WL1', failure_count=1, retry_in_days=-1)],
    )

    assert res.ticker_calls == ['WL1']
    assert [t for t, _ in res.table.updates] == ['WL1']


def test_no_yfinance_info_records_skip():
    """A ticker yfinance can't serve gets a no_yfinance_info skip row with
    failure_count 1 and retry_after ~7 days out."""
    securities = [_sec_row('WL1')]

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        yf_infos={'WL1': {}},  # no info at all
    )

    assert res.ticker_calls == ['WL1']
    upserts = _flattened_upserts(res.skips)
    assert list(upserts) == ['WL1']
    row = upserts['WL1']
    assert row['reason'] == 'no_yfinance_info'
    assert row['failure_count'] == 1
    retry_after = datetime.fromisoformat(row['retry_after'])
    assert timedelta(days=6) < retry_after - datetime.now(timezone.utc) < timedelta(days=8)
    assert 'skips recorded: 1 no_yfinance_info, 0 not_equity, 0 no_fundamentals' in res.message


def test_not_equity_records_skip():
    """An ETF holding with no securities row whose quoteType is not EQUITY
    gets a not_equity skip row."""
    holdings = [_holding('BUZZ', 'HEETF', 'Some Fund', 5.0)]

    res = run_refresh_job(
        watchlist_rows=[],
        securities_rows=[],  # no securities row anywhere
        holdings_rows=holdings,
        yf_infos={'HEETF': {'quoteType': 'ETF'}},
    )

    upserts = _flattened_upserts(res.skips)
    assert list(upserts) == ['HEETF']
    assert upserts['HEETF']['reason'] == 'not_equity'
    assert upserts['HEETF']['failure_count'] == 1
    assert res.table.upserts == []  # nothing inserted into securities
    assert '1 not_equity' in res.message


def test_no_fundamentals_records_skip_but_writes_partial_updates():
    """A fetch that yields no indicator column is recorded as no_fundamentals
    but its partial updates (e.g. trailing_pe) are still written."""
    securities = [_sec_row('WL1'), _sec_row('WL2')]

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}, {'ticker': 'WL2'}],
        securities_rows=securities,
        yf_infos={
            'WL1': {'quoteType': 'EQUITY', 'trailingPE': 9.0},  # no indicator col
            'WL2': {'quoteType': 'EQUITY', 'forwardPE': 12.0},  # healthy
        },
    )

    # Both tickers got their updates written as before
    assert dict(res.table.updates) == {
        'WL1': {'trailing_pe': 9.0},
        'WL2': {'forward_pe': 12.0},
    }
    upserts = _flattened_upserts(res.skips)
    assert list(upserts) == ['WL1']
    assert upserts['WL1']['reason'] == 'no_fundamentals'
    assert res.skips.deletes == []
    assert '1 no_fundamentals' in res.message


def test_success_clears_existing_skip_row():
    """A fetch that fills at least one indicator column deletes the ticker's
    skips row."""
    securities = [_sec_row('WL1')]

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        yf_infos={'WL1': {'quoteType': 'EQUITY', 'forwardPE': 10.0}},
        skips_rows=[_skip_row('WL1', failure_count=4, retry_in_days=-1)],
    )

    assert res.ticker_calls == ['WL1']
    assert res.skips.upserts == []
    assert res.skips.deletes == [['WL1']]
    assert '0 no_fundamentals' in res.message


def test_failure_count_increments_with_growing_retry_after():
    """A repeat failure increments failure_count from the loaded row and
    recomputes a longer retry_after (7d * 2**(n-1))."""
    securities = [_sec_row('WL1')]

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        yf_infos={'WL1': {}},  # fails again with no info
        skips_rows=[_skip_row('WL1', failure_count=2, retry_in_days=-1)],
    )

    upserts = _flattened_upserts(res.skips)
    row = upserts['WL1']
    assert row['failure_count'] == 3
    retry_after = datetime.fromisoformat(row['retry_after'])
    assert timedelta(days=27) < retry_after - datetime.now(timezone.utc) < timedelta(days=29)
    # first_failed_at is preserved from the existing row
    assert row['first_failed_at'] != row['last_failed_at']


def test_yfinance_exception_not_recorded():
    """Transient yfinance exceptions count as errors but are not recorded as
    skips (they may be network blips)."""
    securities = [_sec_row('WL1')]

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        yf_raise={'WL1'},
    )

    assert res.ticker_calls == ['WL1']
    assert res.skips.upserts == []
    assert res.skips.deletes == []
    assert 'watchlist 0 updated, 0 skipped, 1 errors' in res.message
    assert 'skips recorded: 0 no_yfinance_info, 0 not_equity, 0 no_fundamentals' in res.message


def test_skips_table_error_job_still_runs():
    """A missing/unreadable skips table (migration not applied) logs a warning
    and the job carries on without suppressing anything."""
    holdings = [_holding('BUZZ', 'HEAVY', 'Heavy Co', 5.0)]
    securities = [_sec_row('WL1'), _sec_row('HEAVY')]
    infos = {
        'WL1': {'quoteType': 'EQUITY', 'forwardPE': 10.0},
        'HEAVY': {'quoteType': 'EQUITY', 'forwardPE': 20.0},
    }

    res = run_refresh_job(
        watchlist_rows=[{'ticker': 'WL1'}],
        securities_rows=securities,
        holdings_rows=holdings,
        yf_infos=infos,
        skips_error=RuntimeError('relation "fundamentals_fetch_skips" does not exist'),
    )

    assert res.ticker_calls == ['WL1', 'HEAVY']
    assert [t for t, _ in res.table.updates] == ['WL1', 'HEAVY']
    assert '0 suppressed by backoff' in res.message
    assert res.failed.assert_not_called() is None
    assert res.log.call_args.args[1] is True
