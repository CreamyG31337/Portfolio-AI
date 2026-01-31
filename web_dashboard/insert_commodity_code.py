"""
Script to insert commodity chart functions into dashboard.ts
"""

# Read the file
with open('src/js/dashboard.ts', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Define the commodity functions to insert
commodity_functions = """
// ============================================================================
// Commodity Chart Functions
// ============================================================================

async function fetchCommoditiesChart(): Promise<void> {
    showSpinner('commodities-chart-spinner');
    
    const theme = getEffectiveTheme();
    
    // Get selected commodities from checkboxes
    const selected: string[] = [];
    const checkboxes = document.querySelectorAll('.commodity-toggle');
    checkboxes.forEach((cb: Element) => {
        const input = cb as HTMLInputElement;
        if (input.checked) {
            const commodityName = input.id.replace('commodity-', '');
            selected.push(commodityName);
        }
    });
    
    if (selected.length === 0) {
        const chartEl = document.getElementById('commodities-chart');
        if (chartEl) {
            chartEl.innerHTML = '<div class="text-center text-text-secondary py-12"><p>Select at least one commodity to display</p></div>';
        }
        hideSpinner('commodities-chart-spinner');
        return;
    }
    
    const commoditiesParam = selected.join(',');
    const url = `/api/dashboard/charts/commodities?commodities=${encodeURIComponent(commoditiesParam)}&days=365&theme=${encodeURIComponent(theme)}`;
    console.log('[Dashboard] Fetching commodities chart...', { url, selected });
    
    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const data: AllocationChartData = await response.json();
        renderCommoditiesChart(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching commodities chart:', error);
        const chartEl = document.getElementById('commodities-chart');
        if (chartEl) chartEl.innerHTML = '<div class="text-center text-text-secondary py-8"><p>Error loading chart</p></div>';
    } finally {
        hideSpinner('commodities-chart-spinner');
    }
}

function renderCommoditiesChart(data: AllocationChartData): void {
    const chartEl = document.getElementById('commodities-chart');
    if (!chartEl) return;
    
    const Plotly = (window as any).Plotly;
    if (!Plotly) return;
    
    const layout = { ...data.layout };
    layout.height = 400;
    layout.autosize = true;
    layout.margin = { l: 60, r: 20, t: 40, b: 60 };
    
    try {
        Plotly.newPlot('commodities-chart', data.data, layout, {
            responsive: true,
            displayModeBar: false,
            useResizeHandler: true
        });
        
        if (!(window as any).__commoditiesChartResizeHandler) {
            const resizeHandler = () => {
                if (document.getElementById('commodities-chart')) {
                    Plotly.Plots.resize('commodities-chart');
                }
            };
            (window as any).__commoditiesChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }
    } catch (error) {
        console.error('[Dashboard] Error rendering commodities chart:', error);
    }
}

function initCommodityControls(): void {
    const checkboxes = document.querySelectorAll('.commodity-toggle');
    
    if (checkboxes.length === 0) {
        console.warn('[Dashboard] Commodity toggles not found');
        return;
    }
    
    const savedPrefs = localStorage.getItem('commodity_selections');
    if (savedPrefs) {
        try {
            const prefs = JSON.parse(savedPrefs);
            checkboxes.forEach((cb: Element) => {
                const input = cb as HTMLInputElement;
                const commodityName = input.id.replace('commodity-', '');
                if (typeof prefs[commodityName] === 'boolean') {
                    input.checked = prefs[commodityName];
                }
            });
        } catch (e) {
            console.warn('[Dashboard] Error loading commodity preferences:', e);
        }
    }
    
    checkboxes.forEach((cb: Element) => {
        cb.addEventListener('change', (): void => {
            const prefs: { [key: string]: boolean } = {};
            checkboxes.forEach((checkbox: Element) => {
                const input = checkbox as HTMLInputElement;
                const commodityName = input.id.replace('commodity-', '');
                prefs[commodityName] = input.checked;
            });
            localStorage.setItem('commodity_selections', JSON.stringify(prefs));
            fetchCommoditiesChart();
        });
    });
}

"""

# 1. Insert commodity functions after line 1953 (after exchange rate section)
lines.insert(1954, commodity_functions)

# 2. Find and update line 242 to add initCommodityControls()
for i, line in enumerate(lines):
    if 'initExchangeRateControls();' in line and i < 250:
        lines.insert(i + 1, '    initCommodityControls();\r\n')
        break

# 3. Find and update refreshDashboard() to add fetchCommoditiesChart()
for i, line in enumerate(lines):
    if 'fetchExchangeRateData(),' in line:
        lines.insert(i + 1, '            fetchCommoditiesChart(),\r\n')
        break

# 4. Find and update initThemeSync() to add fetch call
for i, line in enumerate(lines):
    if 'fetchExchangeRateData().catch(err' in line and 'theme change' in line:
        lines.insert(i + 1, '            fetchCommoditiesChart().catch(err => console.error(\'[Dashboard] Error refreshing commodities chart on theme change:\', err));\r\n')
        break

# Write back
with open('src/js/dashboard.ts', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Successfully integrated commodity chart functions into dashboard.ts")
print("Added:")
print("  - fetchCommoditiesChart() function")
print("  - renderCommoditiesChart() function")
print("  - initCommodityControls() function")
print("  - Init call in startup")
print("  - Fetch call in refreshDashboard()")
print("  - Theme sync integration")
