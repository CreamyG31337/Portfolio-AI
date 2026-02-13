CREATE OR REPLACE VIEW congress_trades_enriched AS
SELECT ct.id,
    ct.politician_id,
    ct.ticker,
    ct.chamber,
    ct.transaction_date,
    ct.disclosure_date,
    ct.type,
    ct.amount,
    ct.asset_type,
    ct.price,
    ct.party,
    ct.state,
    ct.owner,
    ct.conflict_score,
    ct.notes,
    ct.created_at,
    p.name AS politician,
    p.bioguide_id AS politician_bioguide_id,
    ctr.pct_change,
    ctr.current_price AS current_price_adj,
    ctr.entry_price_adj,
    ctr.last_updated AS return_updated_at
FROM congress_trades ct
JOIN politicians p ON ct.politician_id = p.id
LEFT JOIN congress_trade_returns ctr ON ct.id = ctr.trade_id;
