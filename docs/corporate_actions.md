# Corporate actions

Record every split (or similar) that changes `trade_log` share/price without a
matching back-adjusted price history. The next full rebuild will silently
reintroduce a 2× overstatement if `trade_log` is already adjusted and Yahoo
(or the fallback feed) is not.

## Ledger

| Ticker | Ratio | Ex-date | Funds | Applied | Method |
|---|---|---|---|---|---|
| MNST | 2:1 | 2026-08-11 | RRSP Lance Webull, TFSA | 2026-08-13 | `trade_log` adjust via `debug/apply_stock_split.py` + 6-row targeted `portfolio_positions` repair (`date_only >= 2026-08-10`). **No rebuild.** |

### MNST 2:1 (2026-08-11)

- BUY/SELL notionals and realized P&L unchanged (RRSP $181.48, TFSA $6.83).
- Open shares doubled: RRSP 13 → 26, TFSA 0.489269 → 0.978538. Cost basis
  unchanged ($815.10 / $30.68).
- Positions on 2026-08-10+ were share-doubled in place; prices already
  split-adjusted (except see V14). Pre-split history (through 2026-08-07) is
  still 13 / 0.489269 shares at unadjusted closes — that is correct until
  Yahoo back-adjusts.

#### V14 — capture 2026-08-10 before any rebuild

MNST's **2026-08-10 close exists only in prod `portfolio_positions`**
(`price = 45.72`, already split-adjusted). Yahoo has no 08-10 bar. Any
`rebuild_fund_from_date` run will overwrite it with an F5 carry-forward of
the 08-07 close (90.36) and destroy the live-captured print.

**Before any future rebuild of RRSP Lance Webull or TFSA:**

```sql
create table tmp_mnst_2026_08_10 as
select * from portfolio_positions
where ticker = 'MNST' and date_only = '2026-08-10'
  and fund in ('RRSP Lance Webull', 'TFSA');
```

After the rebuild, restore those two rows (do not let carry-forward stand).

### When a full rebuild becomes safe

Yahoo currently has the split half-applied: the event is recorded, history is
unadjusted, 2026-08-10 and 08-11 are missing. Periodically:

```powershell
.\venv\Scripts\python.exe -c "import yfinance as yf; print(yf.Ticker('MNST').splits.tail(3)); print(yf.Ticker('MNST').history(start='2026-08-05', end='2026-08-13')[['Close']])"
```

Once history is back-adjusted **and** the 08-10/08-11 gaps are filled, a full
rebuild from 2025-09-03 is both safe (post-Phase-1 rebuild fixes) and
desirable. **Still capture the 08-10 row first (V14)** and re-apply it if the
rebuild does not reproduce 45.72.

Until then, do not run `manual_rebuild.py --apply` against production funds
for MNST.

### Admin UI — do not re-corrupt FTS.TO / KO

`infer_trade_action` used to classify any reason containing `\bdividend\b` as
`DIVIDEND`, including a BUY thesis like "decades of dividend growth" (V4).
That labeled the same two tickers on **both** funds:

| Fund | Ticker | Date | Shares | Cost | Repaired |
|---|---|---|---|---|---|
| RRSP Lance Webull | FTS.TO | 2025-08-25 | 47 | 3290.00 | 2026-08-13 (4.3) |
| RRSP Lance Webull | KO | 2025-09-03 | 24 | 1655.28 | 2026-08-13 (4.3) |
| TFSA | FTS.TO | 2025-08-25 | 1.768895 | 123.82 | 2026-08-13 (V16) |
| TFSA | KO | 2025-09-03 | 0.903266 | 62.30 | 2026-08-13 (V16) |

V16 was latent only — TFSA is `reinvest`, so the cash-dividend skip never
fired. Switching TFSA to `cash` without this repair would drop ~$215 on
rebuild.

The classifier now excludes thesis collocations. `admin_routes.py` insert/edit
still fall back to `infer_trade_action` when the payload has no valid
`action`. **Do not edit FTS.TO or KO in the admin UI without confirming the
saved `action` stays `BUY`.** An empty `action` field on edit used to re-infer
from reason and would have undone the repair.

#### Standard check — enumerate non-DRIP `DIVIDEND` rows

A count of `action='DIVIDEND'` hides thesis rows inside real DRIPs (Gate 0
counted "127 of 127 contain a dividend word"). Always enumerate:

```sql
select fund, ticker, date::date, action, shares, left(reason,55)
from trade_log
where action = 'DIVIDEND'
  and reason !~* '^\s*drip\s*$';
```

Must return **zero** rows. Anything listed is a mislabeled BUY (or a cash
dividend that should stay `DIVIDEND` with a non-DRIP reason — inspect before
updating).

## Tooling

See `debug/apply_stock_split.py` and `debug/README.md`. Pair every split
`trade_log` apply with a targeted position UPDATE (`shares = <pre-split>`
guard). Never use a full historical rebuild as the split fix while the
provider's history is unadjusted.
