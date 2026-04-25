"""One-off: write improved_reasons_chimera_rationales.csv (gitignored) for apply_csv_reasons."""
from __future__ import annotations

import csv
from pathlib import Path

# Map user tickers -> trade_log.ticker (Supabase)
_PAIRS: list[tuple[str, str]] = [
    (
        "CCO.TO",
        "Purchased to secure foundational exposure to the global uranium bull market and nuclear "
        "energy renaissance. Serves as a premier, wide-moat tier-one producer providing stability to "
        "the energy pillar.",
    ),
    (
        "CEG",
        "Acquired to capitalize on the increasing power demands of AI data centers and the broader "
        "nuclear energy revival. Provides reliable, clean baseload energy exposure with strong utility "
        "fundamentals.",
    ),
    (
        "CRWD",
        'Purchased as a core holding within the AI and technology pillar to capture the expanding '
        'enterprise cybersecurity market. Represents a "picks and shovels" play on the essential '
        "security layers required for cloud infrastructure.",
    ),
    (
        "CTRN",
        "Acquired as a strategic turnaround play in the off-price retail sector. The investment thesis "
        "relied on fundamental improvements and a recovery in lower-income consumer spending to drive "
        "margin expansion.",
    ),
    (
        "DRX.TO",
        "Purchased as a high-quality industrial fabrication play benefiting from North American "
        "infrastructure spending and onshoring trends. Provides robust fundamental growth and margin "
        "expansion within the industrial core.",
    ),
    (
        "GLO.TO",
        "Acquired as a catalyst-driven venture play within the uranium sector. Offers leveraged upside "
        "potential as it advances its high-grade African uranium project toward near-term production.",
    ),
    (
        "GMIN.TO",
        "Purchased to anchor the precious metals allocation within the materials core, serving as a "
        "hedge against inflation and geopolitical risk. Offers significant growth potential as it "
        "transitions from a developer to an active gold producer.",
    ),
    (
        "HLIT.TO",
        "Acquired as a strategic value play capitalizing on broadband infrastructure upgrades and video "
        "streaming technology. Offers potential upside from its dominant market share in virtualized cable "
        "access solutions.",
    ),
    (
        "LEU",
        "Purchased to gain specialized exposure to the nuclear fuel supply chain and advanced reactor "
        "ecosystem. Serves as a strategic venture play on domestic uranium enrichment capabilities and "
        "HALEU production.",
    ),
    (
        "LTRX",
        "Purchased as a turnaround play in the high-growth Internet of Things (IoT) sector, with specific "
        "applications in 5G routers and defense drones. Offers significant upside potential through margin "
        "expansion as the company achieves non-GAAP profitability and shifts to higher-value software.",
    ),
    (
        "OKLO",
        "Acquired as a high-risk, high-reward venture play on the commercialization of small modular "
        "reactors (SMRs). Capitalizes on the secular trend of providing dedicated, clean baseload power to "
        "massive AI data centers.",
    ),
    (
        "PLTR",
        "Purchased as a high-conviction enterprise software platform within the AI growth engine. "
        "Capitalizes on accelerating revenue growth driven by the commercial adoption of its artificial "
        "intelligence platform.",
    ),
    (
        "PRE",
        "Acquired as a speculative satellite position within the healthcare and genomics sector. Offers "
        "potential value realization from its diagnostic technologies and strategic corporate restructuring.",
    ),
    (
        "QCOM",
        'Purchased to secure exposure to the fabless semiconductor market and the expansion of AI into '
        'edge devices. Serves as a core "picks and shovels" tech holding benefiting from the upgrade '
        "cycle in mobile and IoT computing.",
    ),
    (
        "RAIL",
        "Acquired as a strategic value play benefiting from the modernization of the North American rail "
        "fleet. Offers substantial upside potential driven by margin expansion and increased manufacturing "
        "output.",
    ),
    (
        "SMH",
        'Purchased as the primary "picks and shovels" vehicle to capture the generational technology shift '
        "in artificial intelligence. Provides robust, diversified exposure across the entire semiconductor "
        "value chain, including top designers and foundries.",
    ),
    (
        "TECK.B",
        "Acquired to bolster the materials core with premier exposure to copper and essential industrial "
        "metals. Capitalizes on the global electrification trend and constrained base metal supply.",
    ),
    (
        "TRP.TO",
        "Purchased to provide defensive stability and high dividend yield within the energy pillar. Serves "
        "as a reliable, wide-moat infrastructure holding benefiting from long-term North American natural gas "
        "demand.",
    ),
    (
        "URNJ",
        "Acquired to capture the leveraged, higher-beta upside of uranium exploration and development "
        "companies. Complements the core uranium holdings by acting as a high-growth satellite in the "
        "nuclear energy thesis.",
    ),
    (
        "URNM",
        "Purchased as a foundational building block for the nuclear energy thesis, providing broad exposure "
        "to global uranium producers and physical trusts. Capitalizes on the structural supply deficit in "
        "the uranium market.",
    ),
    (
        "VEE.TO",
        "Acquired to provide broad international diversification and capture growth in emerging economies. "
        "Serves as a strategic satellite position to hedge against domestic market concentration.",
    ),
    (
        "WDC",
        "Purchased as a value-oriented technology play benefiting from the cyclical recovery in memory and "
        "data storage. Capitalizes on the massive data infrastructure and storage requirements of the AI "
        "buildout.",
    ),
    (
        "WEB.V",
        'Purchased as a catalyst-driven venture play within the renewable energy sector, focusing on solar '
        'and battery project development. Aims to capture asymmetric upside triggered by securing '
        'regulatory approvals and selling "ready-to-build" projects to major utilities.',
    ),
    (
        "XMA.TO",
        "Purchased to anchor the foundational materials core and capitalize on regional resource strength. "
        "Serves as a broad hedge against inflation while providing stable exposure to base and precious "
        "metals.",
    ),
    (
        "ZCH.TO",
        "Acquired as a deep value, contrarian play on the stabilization and economic recovery of the "
        "Chinese equity market. Offers uncorrelated, high-reward potential within the strategic thematic "
        "satellites pillar.",
    ),
]


def main() -> Path:
    out = Path(__file__).resolve().parent / "improved_reasons_chimera_rationales.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "reason"])
        w.writeheader()
        for ticker, reason in _PAIRS:
            w.writerow({"ticker": ticker, "reason": reason})
    return out


if __name__ == "__main__":
    p = main()
    print(p)
