"""NAV holder rows used by the Chimera glance page."""

from portfolio_metrics import summarize_nav_holders


def test_summarize_nav_holders_splits_value_by_units() -> None:
    summary = summarize_nav_holders(
        contributor_units={"Alex": 1000.0, "Sam": 500.0, "Gone": 0.0},
        contributor_data={
            "Alex": {"net_contribution": 1000.0},
            "Sam": {"net_contribution": 2000.0},
            "Gone": {"net_contribution": 0.0},
        },
        total_units=1500.0,
        fund_total_value=3000.0,
        display_currency="CAD",
    )

    assert summary["unit_price"] == 2.0
    assert summary["fund_value"] == 3000.0
    assert [row["name"] for row in summary["holders"]] == ["Alex", "Sam"]

    alex, sam = summary["holders"]
    assert alex["current_value"] == 2000.0
    assert alex["gain_loss"] == 1000.0
    assert alex["gain_loss_pct"] == 100.0
    assert round(alex["ownership_pct"], 2) == 66.67

    assert sam["current_value"] == 1000.0
    assert sam["gain_loss"] == -1000.0
    assert sam["gain_loss_pct"] == -50.0


def test_summarize_nav_holders_empty_when_no_units() -> None:
    summary = summarize_nav_holders({}, {}, 0.0, 0.0, "CAD")
    assert summary["holders"] == []
    assert summary["unit_price"] is None
