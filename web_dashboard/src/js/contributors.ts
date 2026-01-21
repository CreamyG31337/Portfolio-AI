/**
 * Contributor Management
 * Handles contributor viewing, splitting, merging, and editing
 */

interface ContributorData {
    id: string;
    name: string;
    email: string | null;
    phone?: string;
    address?: string;
    kyc_status?: string;
}

interface Contribution {
    id: string;
    fund: string;
    contributor: string;
    contributor_id?: string;
    email?: string;
    amount: number;
    contribution_type: 'CONTRIBUTION' | 'WITHDRAWAL';
    timestamp: string;
    notes?: string;
}

// Use a scoped variable to avoid conflicts with users.ts
const contributorManager = {
    contributors: [] as ContributorData[],
    currentContributor: null as ContributorData | null,
    currentContributions: [] as Contribution[]
};

// Tab management
function initTabs(): void {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.getAttribute('id')?.replace('tab-', 'tab-content-');

            // Remove active class from all
            tabButtons.forEach(btn => {
                btn.classList.remove('active', 'border-accent', 'text-accent');
                btn.classList.add('border-transparent', 'text-text-secondary');
            });
            tabContents.forEach(content => content.classList.remove('active'));

            // Add active class to selected
            button.classList.add('active', 'border-accent', 'text-accent');
            button.classList.remove('border-transparent', 'text-text-secondary');

            if (targetTab) {
                const targetContent = document.getElementById(targetTab);
                if (targetContent) {
                    targetContent.classList.add('active');
                }
            }
        });
    });
}

// Load contributors
async function loadContributors(): Promise<void> {
    const loadingEl = document.getElementById('loading-contributors');
    const listEl = document.getElementById('contributors-list');
    const noContributorsEl = document.getElementById('no-contributors');
    const errorEl = document.getElementById('error-contributors');

    if (loadingEl) loadingEl.classList.remove('hidden');
    if (listEl) listEl.classList.add('hidden');
    if (noContributorsEl) noContributorsEl.classList.add('hidden');
    if (errorEl) errorEl.classList.add('hidden');

    try {
        const response = await fetch('/api/admin/contributors');
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load contributors');
        }

        contributorManager.contributors = data.contributors || [];

        if (loadingEl) loadingEl.classList.add('hidden');

        if (contributorManager.contributors.length === 0) {
            if (noContributorsEl) noContributorsEl.classList.remove('hidden');
        } else {
            if (listEl) {
                renderContributors(contributorManager.contributors);
                listEl.classList.remove('hidden');
            }
        }

        // Populate select dropdowns
        populateSelectDropdowns();
        populateAccessDropdowns();

    } catch (error) {
        console.error('Error loading contributors:', error);
        if (loadingEl) loadingEl.classList.add('hidden');
        if (errorEl) {
            errorEl.classList.remove('hidden');
            const errorText = document.getElementById('error-contributors-text');
            if (errorText) {
                errorText.textContent = error instanceof Error ? error.message : 'Failed to load contributors';
            }
        }
    }
}

// Render contributors list
function renderContributors(contribs: ContributorData[]): void {
    const container = document.getElementById('contributors-list');
    if (!container) return;

    container.innerHTML = '';

    contribs.forEach(contrib => {
        const card = document.createElement('div');
        card.className = 'contributor-card bg-dashboard-surface rounded-lg shadow-sm p-6 mb-4 border border-border transition hover:bg-dashboard-surface-alt hover:shadow-md hover:-translate-y-0.5';
        card.innerHTML = `
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <h3 class="text-lg font-semibold text-text-primary mb-1">${escapeHtml(contrib.name)}</h3>
                    <p class="text-sm text-text-secondary mb-2">${contrib.email || 'No email'}</p>
                    <p class="text-xs text-text-secondary">ID: ${contrib.id.substring(0, 8)}...</p>
                </div>
                <button class="view-contributions-btn bg-accent text-white px-4 py-2 rounded-md hover:bg-accent-hover text-sm"
                        data-contributor-id="${contrib.id}">
                    <i class="fas fa-eye mr-1"></i>View Contributions
                </button>
            </div>
            <div id="contributions-${contrib.id}" class="hidden mt-4 pt-4 border-t border-border">
                <div class="text-sm text-text-secondary">Loading contributions...</div>
            </div>
        `;

        container.appendChild(card);

        // Add click handler for view contributions
        const viewBtn = card.querySelector('.view-contributions-btn');
        if (viewBtn) {
            viewBtn.addEventListener('click', () => {
                const contribDiv = document.getElementById(`contributions-${contrib.id}`);
                if (contribDiv) {
                    if (contribDiv.classList.contains('hidden')) {
                        loadContributorContributions(contrib.id, contribDiv);
                        contribDiv.classList.remove('hidden');
                    } else {
                        contribDiv.classList.add('hidden');
                    }
                }
            });
        }
    });
}

// Load contributions for a contributor
async function loadContributorContributions(contributorId: string, container: HTMLElement): Promise<void> {
    try {
        const response = await fetch(`/api/admin/contributors/${contributorId}/contributions`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load contributions');
        }

        const contributions = data.contributions || [];

        if (contributions.length === 0) {
            container.innerHTML = '<p class="text-sm text-text-secondary">No contributions found</p>';
            return;
        }

        // Group by fund
        const byFund: Record<string, Contribution[]> = {};
        contributions.forEach((c: Contribution) => {
            const fund = c.fund || 'Unknown';
            if (!byFund[fund]) {
                byFund[fund] = [];
            }
            byFund[fund].push(c);
        });

        let html = '<div class="space-y-4">';
        for (const [fund, contribs] of Object.entries(byFund)) {
            const net = contribs.reduce((sum, c) => {
                const amount = parseFloat(String(c.amount || 0));
                return sum + (c.contribution_type === 'CONTRIBUTION' ? amount : -amount);
            }, 0);

            html += `
                <div class="bg-dashboard-surface-alt rounded p-3">
                    <h4 class="font-semibold text-text-primary mb-2">${escapeHtml(fund)}</h4>
                    <p class="text-sm text-text-secondary">${contribs.length} transaction(s), Net: $${net.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                </div>
            `;
        }
        html += '</div>';

        container.innerHTML = html;

    } catch (error) {
        console.error('Error loading contributions:', error);
        container.innerHTML = `<p class="text-sm text-theme-error-text">Error: ${error instanceof Error ? error.message : 'Failed to load contributions'}</p>`;
    }
}

// Populate select dropdowns
function populateSelectDropdowns(): void {
    const options = contributorManager.contributors.map(c => ({
        value: c.id,
        text: `${c.name} (${c.email || 'No email'})`
    }));

    // Split contributor select
    const splitSelect = document.getElementById('split-contributor-select') as HTMLSelectElement;
    if (splitSelect) {
        splitSelect.innerHTML = '<option value="">-- Select Contributor --</option>' +
            options.map(opt => `<option value="${opt.value}">${opt.text}</option>`).join('');

        splitSelect.addEventListener('change', (e) => {
            const select = e.target as HTMLSelectElement;
            const contributorId = select.value;
            if (contributorId) {
                loadContributorForSplit(contributorId);
            } else {
                const detailsDiv = document.getElementById('split-contributor-details');
                if (detailsDiv) detailsDiv.classList.add('hidden');
            }
        });
    }

    // Merge selects
    const mergeSource = document.getElementById('merge-source-select') as HTMLSelectElement;
    const mergeTarget = document.getElementById('merge-target-select') as HTMLSelectElement;
    if (mergeSource) {
        mergeSource.innerHTML = '<option value="">-- Select Source --</option>' +
            options.map(opt => `<option value="${opt.value}">${opt.text}</option>`).join('');
    }
    if (mergeTarget) {
        mergeTarget.innerHTML = '<option value="">-- Select Target --</option>' +
            options.map(opt => `<option value="${opt.value}">${opt.text}</option>`).join('');

        // Update merge preview
        if (mergeSource && mergeTarget) {
            const updateMergePreview = () => {
                const sourceId = mergeSource.value;
                const targetId = mergeTarget.value;
                const preview = document.getElementById('merge-preview');
                const btn = document.getElementById('merge-contributors-btn') as HTMLButtonElement;

                if (sourceId && targetId && sourceId !== targetId) {
                    if (preview) {
                        const source = contributorManager.contributors.find(c => c.id === sourceId);
                        const target = contributorManager.contributors.find(c => c.id === targetId);
                        if (source && target) {
                            preview.classList.remove('hidden');
                            const previewText = document.getElementById('merge-preview-text');
                            if (previewText) {
                                previewText.textContent = `Will merge "${source.name}" into "${target.name}"`;
                            }
                        }
                    }
                    if (btn) btn.disabled = false;
                } else {
                    if (preview) preview.classList.add('hidden');
                    if (btn) btn.disabled = true;
                }
            };

            mergeSource.addEventListener('change', updateMergePreview);
            mergeTarget.addEventListener('change', updateMergePreview);
        }
    }

    // Edit select
    const editSelect = document.getElementById('edit-contributor-select') as HTMLSelectElement;
    if (editSelect) {
        editSelect.innerHTML = '<option value="">-- Select Contributor --</option>' +
            options.map(opt => `<option value="${opt.value}">${opt.text}</option>`).join('');

        editSelect.addEventListener('change', (e) => {
            const select = e.target as HTMLSelectElement;
            const contributorId = select.value;
            if (contributorId) {
                loadContributorForEdit(contributorId);
            } else {
                const formDiv = document.getElementById('edit-contributor-form');
                if (formDiv) formDiv.classList.add('hidden');
            }
        });
    }
}

// Load contributor for split
async function loadContributorForSplit(contributorId: string): Promise<void> {
    try {
        const response = await fetch(`/api/admin/contributors/${contributorId}/contributions`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load contributions');
        }

        contributorManager.currentContributor = data.contributor;
        contributorManager.currentContributions = data.contributions || [];

        const detailsDiv = document.getElementById('split-contributor-details');
        if (detailsDiv) {
            detailsDiv.classList.remove('hidden');

            // Render contributions list
            const contribsList = document.getElementById('split-contributions-list');
            if (contribsList) {
                if (contributorManager.currentContributions.length === 0) {
                    contribsList.innerHTML = '<p class="text-sm text-text-secondary">No contributions found</p>';
                } else {
                    contribsList.innerHTML = contributorManager.currentContributions.map((c: Contribution) => {
                        const date = new Date(c.timestamp).toLocaleDateString();
                        const amount = parseFloat(String(c.amount || 0));
                        return `
                            <label class="flex items-center p-2 hover:bg-dashboard-hover rounded cursor-pointer text-text-primary">
                                <input type="checkbox" value="${c.id}" class="mr-3 contribution-checkbox form-checkbox text-accent focus:ring-accent border-border">
                                <span class="flex-1">
                                    ${escapeHtml(c.fund || 'Unknown')} - $${amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} 
                                    (${c.contribution_type}) - ${date}
                                </span>
                            </label>
                        `;
                    }).join('');
                }
            }

            // Enable split button when contributions selected
            const splitBtn = document.getElementById('split-contributor-btn') as HTMLButtonElement;
            const nameInput = document.getElementById('new-contributor-name') as HTMLInputElement;

            const updateSplitButton = () => {
                const checked = document.querySelectorAll('.contribution-checkbox:checked');
                if (splitBtn && nameInput) {
                    splitBtn.disabled = checked.length === 0 || !nameInput.value.trim();
                }
            };

            document.querySelectorAll('.contribution-checkbox').forEach(cb => {
                cb.addEventListener('change', updateSplitButton);
            });

            if (nameInput) {
                nameInput.addEventListener('input', updateSplitButton);
            }
        }

    } catch (error) {
        console.error('Error loading contributor:', error);
        showContributorToast(`Error: ${error instanceof Error ? error.message : 'Failed to load contributor'}`, 'error');
    }
}

// Split contributor
async function splitContributor(): Promise<void> {
    const contributorId = (document.getElementById('split-contributor-select') as HTMLSelectElement)?.value;
    const newName = (document.getElementById('new-contributor-name') as HTMLInputElement)?.value;
    const newEmail = (document.getElementById('new-contributor-email') as HTMLInputElement)?.value;
    const checked = Array.from(document.querySelectorAll('.contribution-checkbox:checked'))
        .map(cb => (cb as HTMLInputElement).value);

    if (!contributorId || !newName || checked.length === 0) {
        showContributorToast('Please fill in all required fields and select at least one contribution', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/admin/contributors/split', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_contributor_id: contributorId,
                new_contributor_name: newName,
                new_contributor_email: newEmail || null,
                contribution_ids: checked
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to split contributor');
        }

        const resultDiv = document.getElementById('split-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-success-bg/20 border border-theme-success-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-success-text">✅ ${data.message}</p>`;
        }

        // Reload contributors
        await loadContributors();

        // Reset form
        (document.getElementById('split-contributor-select') as HTMLSelectElement).value = '';
        (document.getElementById('new-contributor-name') as HTMLInputElement).value = '';
        (document.getElementById('new-contributor-email') as HTMLInputElement).value = '';
        const detailsDiv = document.getElementById('split-contributor-details');
        if (detailsDiv) detailsDiv.classList.add('hidden');

    } catch (error) {
        console.error('Error splitting contributor:', error);
        const resultDiv = document.getElementById('split-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-error-bg/20 border border-theme-error-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-error-text">❌ ${error instanceof Error ? error.message : 'Failed to split contributor'}</p>`;
        }
    }
}

// Merge contributors
async function mergeContributors(): Promise<void> {
    const sourceId = (document.getElementById('merge-source-select') as HTMLSelectElement)?.value;
    const targetId = (document.getElementById('merge-target-select') as HTMLSelectElement)?.value;

    if (!sourceId || !targetId || sourceId === targetId) {
        showContributorToast('Please select different source and target contributors', 'warning');
        return;
    }

    if (!confirm('Are you sure you want to merge these contributors? This cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch('/api/admin/contributors/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_contributor_id: sourceId,
                target_contributor_id: targetId
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to merge contributors');
        }

        const resultDiv = document.getElementById('merge-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-success-bg/20 border border-theme-success-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-success-text">✅ ${data.message}</p>`;
        }

        // Reload contributors
        await loadContributors();

        // Reset form
        (document.getElementById('merge-source-select') as HTMLSelectElement).value = '';
        (document.getElementById('merge-target-select') as HTMLSelectElement).value = '';
        const preview = document.getElementById('merge-preview');
        if (preview) preview.classList.add('hidden');

    } catch (error) {
        console.error('Error merging contributors:', error);
        const resultDiv = document.getElementById('merge-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-error-bg/20 border border-theme-error-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-error-text">❌ ${error instanceof Error ? error.message : 'Failed to merge contributors'}</p>`;
        }
    }
}

// Load contributor for edit
function loadContributorForEdit(contributorId: string): void {
    const contributor = contributorManager.contributors.find(c => c.id === contributorId);
    if (!contributor) return;

    const formDiv = document.getElementById('edit-contributor-form');
    if (formDiv) {
        formDiv.classList.remove('hidden');

        const nameInput = document.getElementById('edit-contributor-name') as HTMLInputElement;
        const emailInput = document.getElementById('edit-contributor-email') as HTMLInputElement;

        if (nameInput) nameInput.value = contributor.name;
        if (emailInput) emailInput.value = contributor.email || '';
    }
}

// Update contributor
async function updateContributor(): Promise<void> {
    const contributorId = (document.getElementById('edit-contributor-select') as HTMLSelectElement)?.value;
    const name = (document.getElementById('edit-contributor-name') as HTMLInputElement)?.value;
    const email = (document.getElementById('edit-contributor-email') as HTMLInputElement)?.value;

    if (!contributorId || !name) {
        showContributorToast('Please select a contributor and enter a name', 'warning');
        return;
    }

    try {
        const response = await fetch(`/api/admin/contributors/${contributorId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                email: email || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to update contributor');
        }

        const resultDiv = document.getElementById('edit-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-success-bg/20 border border-theme-success-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-success-text">✅ ${data.message}</p>`;
        }

        // Reload contributors
        await loadContributors();

    } catch (error) {
        console.error('Error updating contributor:', error);
        const resultDiv = document.getElementById('edit-result');
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            resultDiv.className = 'mt-4 p-4 bg-theme-error-bg/20 border border-theme-error-text/30 rounded-md';
            resultDiv.innerHTML = `<p class="text-theme-error-text">❌ ${error instanceof Error ? error.message : 'Failed to update contributor'}</p>`;
        }
    }
}

// Search functionality
function initSearch(): void {
    const nameSearch = document.getElementById('search-name') as HTMLInputElement;
    const emailSearch = document.getElementById('search-email') as HTMLInputElement;

    const filterContributors = () => {
        const nameFilter = nameSearch?.value.toLowerCase() || '';
        const emailFilter = emailSearch?.value.toLowerCase() || '';

        const filtered = contributorManager.contributors.filter(c => {
            const nameMatch = !nameFilter || c.name.toLowerCase().includes(nameFilter);
            const emailMatch = !emailFilter || (c.email || '').toLowerCase().includes(emailFilter);
            return nameMatch && emailMatch;
        });

        renderContributors(filtered);
    };

    if (nameSearch) nameSearch.addEventListener('input', filterContributors);
    if (emailSearch) emailSearch.addEventListener('input', filterContributors);
}

// Toast Notification System
function showContributorToast(message: string, type: 'success' | 'error' | 'warning' | 'info' = 'success'): void {
    let container = document.getElementById('toast-container-contributors');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container-contributors';
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const borderColor = type === 'error' ? 'border-theme-error-text' :
        type === 'warning' ? 'border-theme-warning-text' :
            type === 'info' ? 'border-theme-info-text' :
                'border-theme-success-text';

    const icon = type === 'error' ? '❌' :
        type === 'warning' ? '⚠️' :
            type === 'info' ? 'ℹ️' :
                '✅';

    toast.className = `flex items-center w-full max-w-xs p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow-lg border-l-4 ${borderColor} transition-opacity duration-300 opacity-100`;
    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal flex items-center gap-2 text-text-primary">
            <span class="text-lg">${icon}</span>
            <span>${escapeHtml(message)}</span>
        </div>
        <button type="button" class="ms-auto -mx-1.5 -my-1.5 bg-dashboard-surface text-text-secondary hover:text-text-primary rounded-lg focus:ring-2 focus:ring-border p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8" aria-label="Close">
            <span class="sr-only">Close</span>
            <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
                <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/>
            </svg>
        </button>
    `;

    const closeBtn = toast.querySelector('button');
    if (closeBtn) {
        closeBtn.onclick = () => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        };
    }
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// User Access Management
interface ContributorUser {
    user_id: string;
    email: string;
    full_name?: string;
}

interface ContributorAccessRecord {
    id: string;
    contributor: string;
    contributor_email: string;
    user_email: string;
    user_name?: string;
    access_level: string;
    granted?: string;
}

let contributorUsers: ContributorUser[] = [];
let contributorAccessRecords: ContributorAccessRecord[] = [];

// Load users for access management
async function loadContributorUsers(): Promise<void> {
    try {
        const response = await fetch('/api/admin/users/list');
        const data = await response.json();
        if (response.ok && data.users) {
            contributorUsers = data.users || [];
            populateAccessDropdowns();
        }
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

// Populate access dropdowns
function populateAccessDropdowns(): void {
    // Contributor select
    const contribSelect = document.getElementById('access-contributor-select') as HTMLSelectElement;
    if (contribSelect) {
        const options = contributorManager.contributors.map(c => ({
            value: c.email || '',
            text: `${c.name} (${c.email || 'No email'})`
        }));
        contribSelect.innerHTML = '<option value="">-- Select Contributor --</option>' +
            options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.text)}</option>`).join('');
    }

    // User select
    const userSelect = document.getElementById('access-user-select') as HTMLSelectElement;
    if (userSelect) {
        const options = contributorUsers.map(u => ({
            value: u.email,
            text: u.full_name ? `${u.full_name} (${u.email})` : u.email
        }));
        userSelect.innerHTML = '<option value="">-- Select User --</option>' +
            options.map(opt => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.text)}</option>`).join('');
    }
}

// Load access records
async function loadContributorAccessRecords(): Promise<void> {
    const loadingEl = document.getElementById('loading-access');
    const tableContainer = document.getElementById('access-table-container');
    const noAccessEl = document.getElementById('no-access');
    const errorEl = document.getElementById('error-access');

    if (loadingEl) loadingEl.classList.remove('hidden');
    if (tableContainer) tableContainer.classList.add('hidden');
    if (noAccessEl) noAccessEl.classList.add('hidden');
    if (errorEl) errorEl.classList.add('hidden');

    try {
        const response = await fetch('/api/admin/contributor-access');
        const data = await response.json();

        if (response.status === 404) {
            if (loadingEl) loadingEl.classList.add('hidden');
            if (errorEl) {
                errorEl.classList.remove('hidden');
                const errorText = document.getElementById('error-access-text');
                if (errorText) {
                    errorText.textContent = data.error || 'Contributor access table not found. Run migration DF_009 first.';
                }
            }
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load access records');
        }

        contributorAccessRecords = data.access || [];

        if (loadingEl) loadingEl.classList.add('hidden');

        if (contributorAccessRecords.length === 0) {
            if (noAccessEl) noAccessEl.classList.remove('hidden');
        } else {
            renderContributorAccessTable();
            if (tableContainer) tableContainer.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error loading access records:', error);
        if (loadingEl) loadingEl.classList.add('hidden');
        if (errorEl) {
            errorEl.classList.remove('hidden');
            const errorText = document.getElementById('error-access-text');
            if (errorText) {
                errorText.textContent = error instanceof Error ? error.message : 'Failed to load access records';
            }
        }
    }
}

// Render access table
function renderContributorAccessTable(): void {
    const tbody = document.getElementById('access-table-body');
    if (!tbody) return;

    tbody.innerHTML = contributorAccessRecords.map(access => `
        <tr>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(access.contributor)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtml(access.contributor_email)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(access.user_email)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtml(access.user_name || '')}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">
                <span class="px-2 py-1 text-xs font-semibold rounded-full bg-theme-info-bg/20 text-theme-info-text">${escapeHtml(access.access_level)}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtml(access.granted || '')}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">
                <button class="revoke-access-btn text-theme-error-text hover:text-theme-error-text/80" 
                        data-contributor-email="${escapeHtml(access.contributor_email)}" 
                        data-user-email="${escapeHtml(access.user_email)}">
                    <i class="fas fa-ban mr-1"></i>Revoke
                </button>
            </td>
        </tr>
    `).join('');

    // Attach revoke handlers
    document.querySelectorAll('.revoke-access-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLElement;
            const contributorEmail = target.dataset.contributorEmail || '';
            const userEmail = target.dataset.userEmail || '';
            if (contributorEmail && userEmail) {
                await revokeContributorAccess(contributorEmail, userEmail);
            }
        });
    });
}

// Grant access
async function grantContributorAccess(): Promise<void> {
    const contributorEmail = (document.getElementById('access-contributor-select') as HTMLSelectElement)?.value;
    const userEmail = (document.getElementById('access-user-select') as HTMLSelectElement)?.value;
    const accessLevel = (document.getElementById('access-level-select') as HTMLSelectElement)?.value;
    const resultDiv = document.getElementById('grant-access-result');

    if (!contributorEmail || !userEmail) {
        showContributorToast('Please select both contributor and user', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/admin/contributor-access/grant', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contributor_email: contributorEmail,
                user_email: userEmail,
                access_level: accessLevel
            })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showContributorToast(data.message || 'Access granted', 'success');
            if (resultDiv) {
                resultDiv.classList.add('hidden');
            }

            // Clear form
            (document.getElementById('access-contributor-select') as HTMLSelectElement).value = '';
            (document.getElementById('access-user-select') as HTMLSelectElement).value = '';
            (document.getElementById('access-level-select') as HTMLSelectElement).value = 'viewer';

            // Reload access records
            await loadContributorAccessRecords();
        } else {
            showContributorToast(data.error || data.message || 'Failed to grant access', 'error');
        }
    } catch (error) {
        showContributorToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

// Revoke access
async function revokeContributorAccess(contributorEmail: string, userEmail: string): Promise<void> {
    if (!confirm(`Revoke access for ${userEmail} to ${contributorEmail}?`)) {
        return;
    }

    try {
        const response = await fetch('/api/admin/contributor-access/revoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contributor_email: contributorEmail,
                user_email: userEmail
            })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showContributorToast(data.message || 'Access revoked', 'success');
            await loadContributorAccessRecords();
        } else {
            showContributorToast(data.error || data.message || 'Failed to revoke access', 'error');
        }
    } catch (error) {
        showContributorToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

// Utility function
function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initSearch();
    loadContributors();
    loadContributorUsers();

    // Refresh button
    const refreshBtn = document.getElementById('refresh-contributors-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadContributors());
    }

    // Split button
    const splitBtn = document.getElementById('split-contributor-btn');
    if (splitBtn) {
        splitBtn.addEventListener('click', () => splitContributor());
    }

    // Merge button
    const mergeBtn = document.getElementById('merge-contributors-btn');
    if (mergeBtn) {
        mergeBtn.addEventListener('click', () => mergeContributors());
    }

    // Save button
    const saveBtn = document.getElementById('save-contributor-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', () => updateContributor());
    }

    // Access tab - load access records when tab is clicked
    const accessTab = document.getElementById('tab-access');
    if (accessTab) {
        accessTab.addEventListener('click', () => {
            loadContributorAccessRecords();
        });
    }

    // Grant access button
    const grantAccessBtn = document.getElementById('grant-access-btn');
    if (grantAccessBtn) {
        grantAccessBtn.addEventListener('click', () => grantContributorAccess());
    }
});
