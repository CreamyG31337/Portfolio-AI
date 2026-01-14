export type Theme = 'system' | 'light' | 'dark' | 'midnight-tokyo' | 'abyss';
export type EffectiveTheme = Exclude<Theme, 'system'>;
export type ThemeChangeCallback = (theme: Theme) => void;

export interface PortfolioMetrics {
    total_value?: number;
    performance_pct?: number;
    unrealized_pnl?: number;
    total_trades?: number;
}

export interface Position {
    ticker: string;
    shares: number;
    price: number;
    market_value: number;
    pnl: number;
    pnl_pct: number;
}

export interface Trade {
    ticker: string;
    date: string;
    reason: string;
    shares: number;
    price: number;
    cost_basis: number;
    pnl: number;
}

export interface Contributor {
    contributor: string;
    email?: string;
    net_contribution: number;
    ownership_percentage: number;
    transaction_count: number;
    first_contribution: string;
}

export interface ContributorsResponse {
    contributors: Contributor[];
    total_contributors: number;
    total_net_contributions: number;
}

export interface PortfolioResponse {
    metrics: PortfolioMetrics;
    positions: Position[];
    cash_balances: Record<string, number>;
    available_funds: string[];
    current_fund?: string;
}

export interface ApiResponse {
    success: boolean;
    error?: string;
    [key: string]: any;
}

export interface MoverItem {
    ticker: string;
    company_name?: string;
    daily_pnl_pct?: number;
    daily_pnl?: number;
    five_day_pnl_pct?: number;
    five_day_pnl?: number;
    return_pct?: number;       // total return %
    total_return_pct?: number; // Normalized field name in frontend
    total_pnl?: number;
    current_price?: number;
    market_value?: number;
}

export interface MoversData {
    gainers: MoverItem[];
    losers: MoverItem[];
    display_currency: string;
    processing_time?: number;
}
