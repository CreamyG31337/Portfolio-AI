/**
 * User & Access Management Dashboard
 * Handles user management, contributor access, and all related operations
 */

// Type definitions
interface User {
    user_id: string;
    email: string;
    full_name?: string;
    role?: string;
    funds?: string[];
}

interface Contributor {
    id: string;
    name: string;
    email?: string;
}

interface UnregisteredContributor {
    contributor: string;
    email?: string;
    funds?: string[];
    total_contribution?: number;
}

interface AccessRecord {
    id: string;
    contributor: string;
    contributor_email: string;
    user_email: string;
    user_name?: string;
    access_level: string;
    granted?: string;
}

interface UsersResponse {
    users: User[];
    stats: {
        total_users: number;
        total_funds: number;
        total_assignments: number;
    };
}

interface ContributorsResponse {
    contributors: Contributor[];
}

interface UnregisteredContributorsResponse {
    contributors: UnregisteredContributor[];
}

interface AccessResponse {
    access: AccessRecord[];
}

interface ApiResponse {
    success?: boolean;
    error?: string;
    message?: string;
    already_assigned?: boolean;
    updates_made?: string[];
}

interface ContributorSelectData {
    type: 'contributor' | 'fund_contribution' | 'user';
    id: string | null;
    name: string;
    email: string;
}

interface UsersDOMElements {
    // Tabs
    tabUsers: HTMLElement | null;
    tabAccess: HTMLElement | null;
    tabContentUsers: HTMLElement | null;
    tabContentAccess: HTMLElement | null;

    // User Management
    statsText: HTMLElement | null;
    refreshUsersBtn: HTMLElement | null;
    loadingUsers: HTMLElement | null;
    usersList: HTMLElement | null;
    noUsers: HTMLElement | null;
    errorUsers: HTMLElement | null;
    errorUsersText: HTMLElement | null;

    // Update Email
    contributorSelect: HTMLSelectElement | null;
    newEmailInput: HTMLInputElement | null;
    currentEmailText: HTMLElement | null;
    updateEmailBtn: HTMLButtonElement | null;
    updateEmailResult: HTMLElement | null;

    // Unregistered
    loadingUnregistered: HTMLElement | null;
    unregisteredList: HTMLElement | null;
    noUnregistered: HTMLElement | null;
    errorUnregistered: HTMLElement | null;
    errorUnregisteredText: HTMLElement | null;

    // Contributor Access
    grantContributorSelect: HTMLSelectElement | null;
    grantUserSelect: HTMLSelectElement | null;
    grantAccessLevelSelect: HTMLSelectElement | null;
    grantAccessBtn: HTMLButtonElement | null;
    grantAccessResult: HTMLElement | null;

    // Access Table
    loadingAccess: HTMLElement | null;
    accessTableContainer: HTMLElement | null;
    accessTableBody: HTMLElement | null;
    noAccess: HTMLElement | null;
    errorAccess: HTMLElement | null;
    errorAccessText: HTMLElement | null;

    // Revoke Access
    revokeContributorSelect: HTMLSelectElement | null;
    revokeUserSelect: HTMLSelectElement | null;
    revokeAccessBtn: HTMLButtonElement | null;
    revokeAccessResult: HTMLElement | null;
}

// State
let users: User[] = [];
let contributors: Contributor[] = [];
let funds: string[] = [];
let unregisteredContributors: UnregisteredContributor[] = [];
let accessRecords: AccessRecord[] = [];
let canModify = true; // Will be updated from API
let currentUserEmail = '';

// DOM Elements
const elements: UsersDOMElements = {
    // Tabs
    tabUsers: document.getElementById('tab-users'),
    tabAccess: document.getElementById('tab-access'),
    tabContentUsers: document.getElementById('tab-content-users'),
    tabContentAccess: document.getElementById('tab-content-access'),

    // User Management
    statsText: document.getElementById('stats-text'),
    refreshUsersBtn: document.getElementById('refresh-users-btn'),
    loadingUsers: document.getElementById('loading-users'),
    usersList: document.getElementById('users-list'),
    noUsers: document.getElementById('no-users'),
    errorUsers: document.getElementById('error-users'),
    errorUsersText: document.getElementById('error-users-text'),

    // Update Email
    contributorSelect: document.getElementById('contributor-select') as HTMLSelectElement | null,
    newEmailInput: document.getElementById('new-email-input') as HTMLInputElement | null,
    currentEmailText: document.getElementById('current-email-text'),
    updateEmailBtn: document.getElementById('update-email-btn') as HTMLButtonElement | null,
    updateEmailResult: document.getElementById('update-email-result'),

    // Unregistered
    loadingUnregistered: document.getElementById('loading-unregistered'),
    unregisteredList: document.getElementById('unregistered-list'),
    noUnregistered: document.getElementById('no-unregistered'),
    errorUnregistered: document.getElementById('error-unregistered'),
    errorUnregisteredText: document.getElementById('error-unregistered-text'),

    // Contributor Access
    grantContributorSelect: document.getElementById('grant-contributor-select') as HTMLSelectElement | null,
    grantUserSelect: document.getElementById('grant-user-select') as HTMLSelectElement | null,
    grantAccessLevelSelect: document.getElementById('grant-access-level-select') as HTMLSelectElement | null,
    grantAccessBtn: document.getElementById('grant-access-btn') as HTMLButtonElement | null,
    grantAccessResult: document.getElementById('grant-access-result'),

    // Access Table
    loadingAccess: document.getElementById('loading-access'),
    accessTableContainer: document.getElementById('access-table-container'),
    accessTableBody: document.getElementById('access-table-body'),
    noAccess: document.getElementById('no-access'),
    errorAccess: document.getElementById('error-access'),
    errorAccessText: document.getElementById('error-access-text'),

    // Revoke Access
    revokeContributorSelect: document.getElementById('revoke-contributor-select') as HTMLSelectElement | null,
    revokeUserSelect: document.getElementById('revoke-user-select') as HTMLSelectElement | null,
    revokeAccessBtn: document.getElementById('revoke-access-btn') as HTMLButtonElement | null,
    revokeAccessResult: document.getElementById('revoke-access-result')
};

// Initialize
document.addEventListener('DOMContentLoaded', (): void => {
    fetchUsers();
    fetchFunds();
    fetchContributors();
    fetchUnregisteredContributors();
    fetchAccessRecords();

    // Tab switching
    if (elements.tabUsers) {
        elements.tabUsers.addEventListener('click', () => switchUsersTab('users'));
    }
    if (elements.tabAccess) {
        elements.tabAccess.addEventListener('click', () => switchUsersTab('access'));
    }

    // User Management
    if (elements.refreshUsersBtn) {
        elements.refreshUsersBtn.addEventListener('click', fetchUsers);
    }

    // Update Email
    if (elements.contributorSelect) {
        elements.contributorSelect.addEventListener('change', handleContributorSelectChange);
    }
    if (elements.updateEmailBtn) {
        elements.updateEmailBtn.addEventListener('click', handleUpdateEmail);
    }

    // Grant Access
    if (elements.grantAccessBtn) {
        elements.grantAccessBtn.addEventListener('click', handleGrantAccess);
    }

    // Revoke Access
    if (elements.revokeAccessBtn) {
        elements.revokeAccessBtn.addEventListener('click', handleRevokeAccess);
    }
});

// Tab Switching
function switchUsersTab(tabName: 'users' | 'access'): void {
    // Update tab buttons
    if (tabName === 'users') {
        if (elements.tabUsers) {
            elements.tabUsers.classList.add('active', 'border-accent', 'text-accent');
            elements.tabUsers.classList.remove('border-transparent', 'text-text-secondary');
        }
        if (elements.tabAccess) {
            elements.tabAccess.classList.remove('active', 'border-accent', 'text-accent');
            elements.tabAccess.classList.add('border-transparent', 'text-text-secondary');
        }

        if (elements.tabContentUsers) {
            elements.tabContentUsers.classList.add('active');
        }
        if (elements.tabContentAccess) {
            elements.tabContentAccess.classList.remove('active');
        }
    } else {
        if (elements.tabAccess) {
            elements.tabAccess.classList.add('active', 'border-accent', 'text-accent');
            elements.tabAccess.classList.remove('border-transparent', 'text-text-secondary');
        }
        if (elements.tabUsers) {
            elements.tabUsers.classList.remove('active', 'border-accent', 'text-accent');
            elements.tabUsers.classList.add('border-transparent', 'text-text-secondary');
        }

        if (elements.tabContentAccess) {
            elements.tabContentAccess.classList.add('active');
        }
        if (elements.tabContentUsers) {
            elements.tabContentUsers.classList.remove('active');
        }

        // Load access data when switching to access tab
        fetchAccessRecords();
    }
}

// Fetch Users
async function fetchUsers(): Promise<void> {
    try {
        if (elements.loadingUsers) elements.loadingUsers.classList.remove('hidden');
        if (elements.usersList) elements.usersList.classList.add('hidden');
        if (elements.noUsers) elements.noUsers.classList.add('hidden');
        if (elements.errorUsers) elements.errorUsers.classList.add('hidden');

        const response = await fetch('/api/admin/users/list');
        const data: UsersResponse = await response.json();

        if (!response.ok) {
            throw new Error((data as unknown as ApiResponse).error || 'Failed to fetch users');
        }

        users = data.users || [];

        // Update stats
        if (elements.statsText) {
            elements.statsText.textContent = `${data.stats.total_users} users, ${data.stats.total_funds} funds, ${data.stats.total_assignments} assignments`;
        }

        renderUsers();

        if (elements.loadingUsers) elements.loadingUsers.classList.add('hidden');
        if (elements.usersList) elements.usersList.classList.remove('hidden');

        // Update contributor select for email update
        updateContributorSelect();

        // Update user selects for access management
        updateUserSelects();
    } catch (error) {
        console.error('Error fetching users:', error);
        if (elements.loadingUsers) elements.loadingUsers.classList.add('hidden');
        if (elements.errorUsers) {
            elements.errorUsers.classList.remove('hidden');
            if (elements.errorUsersText) {
                elements.errorUsersText.textContent = error instanceof Error ? error.message : String(error);
            }
        }
    }
}

// Fetch Funds
async function fetchFunds(): Promise<void> {
    try {
        const response = await fetch('/api/admin/funds');
        const data = await response.json();

        if (response.ok) {
            funds = data.funds || [];
        }
    } catch (error) {
        console.error('Error fetching funds:', error);
    }
}

// Fetch Contributors
async function fetchContributors(): Promise<void> {
    try {
        const response = await fetch('/api/admin/contributors');
        const data: ContributorsResponse = await response.json();

        if (response.ok) {
            contributors = data.contributors || [];
            updateContributorSelects();
        }
    } catch (error) {
        console.error('Error fetching contributors:', error);
    }
}

// Fetch Unregistered Contributors
async function fetchUnregisteredContributors(): Promise<void> {
    try {
        if (elements.loadingUnregistered) elements.loadingUnregistered.classList.remove('hidden');
        if (elements.unregisteredList) elements.unregisteredList.classList.add('hidden');
        if (elements.noUnregistered) elements.noUnregistered.classList.add('hidden');
        if (elements.errorUnregistered) elements.errorUnregistered.classList.add('hidden');

        const response = await fetch('/api/admin/contributors/unregistered');
        const data: UnregisteredContributorsResponse = await response.json();

        if (response.status === 404) {
            // Table doesn't exist
            if (elements.loadingUnregistered) elements.loadingUnregistered.classList.add('hidden');
            if (elements.errorUnregistered) {
                elements.errorUnregistered.classList.remove('hidden');
                if (elements.errorUnregisteredText) {
                    elements.errorUnregisteredText.textContent = (data as unknown as ApiResponse).error || 'Contributors table not found. Run migration DF_009 first.';
                }
            }
            return;
        }

        if (!response.ok) {
            throw new Error((data as unknown as ApiResponse).error || 'Failed to fetch unregistered contributors');
        }

        unregisteredContributors = data.contributors || [];

        if (unregisteredContributors.length === 0) {
            if (elements.loadingUnregistered) elements.loadingUnregistered.classList.add('hidden');
            if (elements.noUnregistered) elements.noUnregistered.classList.remove('hidden');
        } else {
            renderUnregisteredContributors();
            if (elements.loadingUnregistered) elements.loadingUnregistered.classList.add('hidden');
            if (elements.unregisteredList) elements.unregisteredList.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error fetching unregistered contributors:', error);
        if (elements.loadingUnregistered) elements.loadingUnregistered.classList.add('hidden');
        if (elements.errorUnregistered) {
            elements.errorUnregistered.classList.remove('hidden');
            if (elements.errorUnregisteredText) {
                elements.errorUnregisteredText.textContent = error instanceof Error ? error.message : String(error);
            }
        }
    }
}

// Fetch Access Records
async function fetchAccessRecords(): Promise<void> {
    try {
        if (elements.loadingAccess) elements.loadingAccess.classList.remove('hidden');
        if (elements.accessTableContainer) elements.accessTableContainer.classList.add('hidden');
        if (elements.noAccess) elements.noAccess.classList.add('hidden');
        if (elements.errorAccess) elements.errorAccess.classList.add('hidden');

        const response = await fetch('/api/admin/contributor-access');
        const data: AccessResponse = await response.json();

        if (response.status === 404) {
            // Table doesn't exist
            if (elements.loadingAccess) elements.loadingAccess.classList.add('hidden');
            if (elements.errorAccess) {
                elements.errorAccess.classList.remove('hidden');
                if (elements.errorAccessText) {
                    elements.errorAccessText.textContent = (data as unknown as ApiResponse).error || 'Contributor access table not found. Run migration DF_009 first.';
                }
            }
            return;
        }

        if (!response.ok) {
            throw new Error((data as unknown as ApiResponse).error || 'Failed to fetch access records');
        }

        accessRecords = data.access || [];

        if (accessRecords.length === 0) {
            if (elements.loadingAccess) elements.loadingAccess.classList.add('hidden');
            if (elements.noAccess) elements.noAccess.classList.remove('hidden');
        } else {
            renderAccessTable();
            if (elements.loadingAccess) elements.loadingAccess.classList.add('hidden');
            if (elements.accessTableContainer) elements.accessTableContainer.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error fetching access records:', error);
        if (elements.loadingAccess) elements.loadingAccess.classList.add('hidden');
        if (elements.errorAccess) {
            elements.errorAccess.classList.remove('hidden');
            if (elements.errorAccessText) {
                elements.errorAccessText.textContent = error instanceof Error ? error.message : String(error);
            }
        }
    }
}

// Render Users
function renderUsers(): void {
    if (users.length === 0) {
        if (elements.noUsers) elements.noUsers.classList.remove('hidden');
        return;
    }

    if (elements.noUsers) elements.noUsers.classList.add('hidden');

    if (!elements.usersList) return;

    const html = users.map(user => createUserCard(user)).join('');
    elements.usersList.innerHTML = html;

    // Attach event listeners
    document.querySelectorAll('.user-action-btn').forEach(btn => {
        btn.addEventListener('click', handleUserAction);
    });
}

function createUserCard(user: User): string {
    const email = user.email || '';
    const fullName = user.full_name || 'N/A';
    const role = user.role || 'user';
    const fundsList = user.funds || [];
    const isAdmin = role === 'admin';
    const isSelf = email === currentUserEmail;

    const fundsStr = fundsList.length > 0
        ? (fundsList.join(', ').length > 30
            ? fundsList.join(', ').substring(0, 27) + '...'
            : fundsList.join(', '))
        : 'No funds';

    return `
        <div class="user-card bg-dashboard-surface rounded-lg shadow p-6 border border-border">
            <div class="flex items-start justify-between">
                <div class="flex-1">
                    <div class="flex items-center space-x-3 mb-2">
                        <h3 class="text-lg font-semibold text-text-primary">${escapeHtmlForUsers(fullName)}</h3>
                        <span class="role-badge ${isAdmin ? 'role-admin' : 'role-user'}">
                            ${isAdmin ? '🔑 Admin' : '👤 User'}
                        </span>
                    </div>
                    <p class="text-sm text-text-secondary mb-2">${escapeHtmlForUsers(email)}</p>
                    <p class="text-sm text-text-secondary">📊 ${escapeHtmlForUsers(fundsStr)}</p>
                </div>
                <div class="action-popover">
                    <button class="user-action-btn bg-dashboard-background hover:bg-dashboard-hover px-3 py-2 rounded-md text-sm border border-border text-text-primary" 
                            data-email="${escapeHtmlForUsers(email)}" data-role="${role}" data-is-self="${isSelf}">
                        <i class="fas fa-cog mr-1"></i>Actions
                    </button>
                </div>
            </div>
        </div>
    `;
}

// Handle User Actions
async function handleUserAction(e: Event): Promise<void> {
    const btn = e.currentTarget as HTMLButtonElement;
    const email = btn.dataset.email || '';
    const role = btn.dataset.role || '';
    const isSelf = btn.dataset.isSelf === 'true';

    // Show action menu (simplified - in production, use a proper dropdown)
    const action = await showActionMenu(email, role, isSelf);
    if (!action) return;

    // Handle the action
    switch (action) {
        case 'grant-admin':
            await grantAdminRole(email);
            break;
        case 'revoke-admin':
            await revokeAdminRole(email, isSelf);
            break;
        case 'assign-fund':
            await showAssignFundDialog(email);
            break;
        case 'remove-fund':
            await showRemoveFundDialog(email);
            break;
        case 'send-invite':
            await sendInvite(email);
            break;
        case 'delete':
            await deleteUser(email);
            break;
    }
}

// Show Action Menu (simplified - use a proper modal/dropdown in production)
async function showActionMenu(email: string, role: string, isSelf: boolean): Promise<string | null> {
    return new Promise((resolve) => {
        const menu = document.createElement('div');
        menu.className = 'fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center';
        menu.innerHTML = `
            <div class="bg-dashboard-surface rounded-lg shadow-2xl border-2 border-border max-w-md w-full mx-4">
                <div class="border-b border-border px-6 py-4 bg-dashboard-background rounded-t-lg">
                    <h3 class="text-lg font-bold text-text-primary">Actions for User</h3>
                    <p class="text-sm text-text-secondary mt-1">${escapeHtmlForUsers(email)}</p>
                </div>
                <div class="p-6 space-y-2">
                    ${role !== 'admin'
                ? `<button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-text-primary" data-action="grant-admin">
                            <i class="fas fa-shield-alt mr-2 text-theme-info-text"></i>Grant Admin
                           </button>`
                : `<button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-text-primary ${isSelf ? 'opacity-50 cursor-not-allowed' : ''}" 
                                 data-action="revoke-admin" ${isSelf ? 'disabled' : ''}>
                            <i class="fas fa-shield-alt mr-2 text-theme-warning-text"></i>Revoke Admin
                           </button>`}
                    <button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-text-primary" data-action="assign-fund">
                        <i class="fas fa-plus-circle mr-2 text-theme-success-text"></i>Assign Fund
                    </button>
                    <button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-text-primary" data-action="remove-fund">
                        <i class="fas fa-minus-circle mr-2 text-theme-warning-text"></i>Remove Fund
                    </button>
                    <button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-text-primary" data-action="send-invite">
                        <i class="fas fa-envelope mr-2 text-theme-info-text"></i>Send Invite
                    </button>
                    <div class="border-t border-border my-2"></div>
                    <button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors text-theme-error-text font-medium" data-action="delete">
                        <i class="fas fa-trash-alt mr-2"></i>Delete User
                    </button>
                    <button class="action-menu-btn w-full text-left px-4 py-3 hover:bg-dashboard-hover rounded-md border border-transparent hover:border-border transition-colors mt-2 text-text-primary" data-action="cancel">
                        <i class="fas fa-times mr-2"></i>Cancel
                    </button>
                </div>
            </div>
        `;

        // Close on backdrop click
        menu.addEventListener('click', (e: Event) => {
            if (e.target === menu) {
                document.body.removeChild(menu);
                resolve(null);
            }
        });

        menu.querySelectorAll('.action-menu-btn').forEach(btn => {
            btn.addEventListener('click', (e: Event) => {
                e.stopPropagation();
                const action = (e.currentTarget as HTMLElement).dataset.action;
                document.body.removeChild(menu);
                if (action !== 'cancel') {
                    resolve(action || null);
                } else {
                    resolve(null);
                }
            });
        });

        document.body.appendChild(menu);
    });
}

// User Actions
async function grantAdminRole(email: string): Promise<void> {
    if (!confirm(`Grant admin role to ${email}?`)) return;

    try {
        const response = await fetch('/api/admin/users/grant-admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email })
        });

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            showToast(data.message || 'Admin role granted', 'success');
            fetchUsers();
        } else {
            showToast(data.error || data.message || 'Failed to grant admin role', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

async function revokeAdminRole(email: string, isSelf: boolean): Promise<void> {
    if (isSelf) {
        showToast('Cannot remove your own admin role', 'warning');
        return;
    }

    if (!confirm(`Revoke admin role from ${email}?`)) return;

    try {
        const response = await fetch('/api/admin/users/revoke-admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email })
        });

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            showToast(data.message || 'Admin role revoked', 'success');
            fetchUsers();
        } else {
            showToast(data.error || data.message || 'Failed to revoke admin role', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

async function showAssignFundDialog(email: string): Promise<void> {
    if (funds.length === 0) {
        showToast('No funds available', 'warning');
        return;
    }

    const fund = prompt(`Assign fund to ${email}:\n\nAvailable funds: ${funds.join(', ')}`);
    if (!fund || !funds.includes(fund)) {
        return;
    }

    try {
        const response = await fetch('/api/admin/assign-fund', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email, fund_name: fund })
        });

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            showToast(data.message || 'Fund assigned', 'success');
            fetchUsers();
        } else if (data.already_assigned) {
            showToast(data.message || 'Fund already assigned', 'warning');
        } else {
            showToast(data.error || data.message || 'Failed to assign fund', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

async function showRemoveFundDialog(email: string): Promise<void> {
    const user = users.find(u => u.email === email);
    if (!user || !user.funds || user.funds.length === 0) {
        showToast('User has no funds assigned', 'warning');
        return;
    }

    const fund = prompt(`Remove fund from ${email}:\n\nAssigned funds: ${user.funds.join(', ')}`);
    if (!fund || !user.funds.includes(fund)) {
        return;
    }

    try {
        const response = await fetch('/api/admin/remove-fund', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email, fund_name: fund })
        });

        const data: ApiResponse = await response.json();

        if (response.ok) {
            showToast(data.message || 'Fund removed', 'success');
            fetchUsers();
        } else {
            showToast(data.error || 'Failed to remove fund', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

async function sendInvite(email: string): Promise<void> {
    try {
        const response = await fetch('/api/admin/users/send-invite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email })
        });

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            showToast(data.message || 'Invite sent', 'success');
        } else {
            showToast(data.error || 'Failed to send invite', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

async function deleteUser(email: string): Promise<void> {
    if (!confirm(`⚠️ Delete user ${email}?\n\nThis cannot be undone. Contributors cannot be deleted.`)) {
        return;
    }

    if (!confirm(`Are you absolutely sure you want to delete ${email}?`)) {
        return;
    }

    try {
        const response = await fetch('/api/admin/users/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_email: email })
        });

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            showToast(data.message || 'User deleted', 'success');
            fetchUsers();
        } else {
            showToast(data.error || data.message || 'Failed to delete user', 'error');
        }
    } catch (error) {
        showToast(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    }
}

// Update Contributor Email
function updateContributorSelect(): void {
    if (!elements.contributorSelect) return;

    const options: string[] = ['<option value="">-- Select --</option>'];

    // Add contributors from contributors table
    contributors.forEach(c => {
        const name = c.name || '';
        const email = c.email || '';
        const display = email ? `${name} (${email}) [Contributor]` : `${name} (no email) [Contributor]`;
        const data: ContributorSelectData = { type: 'contributor', id: c.id, name, email };
        const jsonValue = JSON.stringify(data).replace(/"/g, '&quot;');
        options.push(`<option value="${jsonValue}">${escapeHtmlForUsers(display)}</option>`);
    });

    // Add registered users
    users.forEach(u => {
        const name = u.full_name || u.email || '';
        const email = u.email || '';
        const display = name && email ? `${name} (${email}) [Registered User]` : `${email} [Registered User]`;
        const data: ContributorSelectData = { type: 'user', id: u.user_id, name, email };
        const jsonValue = JSON.stringify(data).replace(/"/g, '&quot;');
        options.push(`<option value="${jsonValue}">${escapeHtmlForUsers(display)}</option>`);
    });

    elements.contributorSelect.innerHTML = options.join('');
}

function handleContributorSelectChange(): void {
    if (!elements.contributorSelect || !elements.newEmailInput || !elements.currentEmailText || !elements.updateEmailBtn) return;

    const selected = elements.contributorSelect.value;
    if (!selected) {
        elements.newEmailInput.disabled = true;
        elements.newEmailInput.value = '';
        elements.currentEmailText.textContent = '';
        elements.updateEmailBtn.disabled = true;
        return;
    }

    try {
        // Decode HTML entities before parsing JSON
        const decodedValue = selected.replace(/&quot;/g, '"');
        const data: ContributorSelectData = JSON.parse(decodedValue);
        elements.newEmailInput.disabled = false;
        elements.newEmailInput.value = '';
        elements.currentEmailText.textContent = `Current email: ${data.email || 'None'}`;
        elements.updateEmailBtn.disabled = false;
    } catch (e) {
        console.error('Error parsing contributor data:', e);
    }
}

async function handleUpdateEmail(): Promise<void> {
    if (!elements.contributorSelect || !elements.newEmailInput || !elements.updateEmailResult) return;

    const selected = elements.contributorSelect.value;
    const newEmail = elements.newEmailInput.value.trim();

    if (!selected || !newEmail) {
        showToast('Please select a contributor and enter a new email address', 'warning');
        return;
    }

    try {
        // Decode HTML entities before parsing JSON
        const decodedValue = selected.replace(/&quot;/g, '"');
        const data: ContributorSelectData = JSON.parse(decodedValue);

        const response = await fetch('/api/admin/users/update-contributor-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contributor_name: data.name,
                contributor_id: data.id,
                contributor_type: data.type,
                new_email: newEmail
            })
        });

        const result: ApiResponse = await response.json();

        if (response.ok && result.success) {
            elements.updateEmailResult.className = 'mt-4 bg-theme-success-bg border border-theme-success-text rounded-lg p-4';
            elements.updateEmailResult.innerHTML = `<i class="fas fa-check-circle text-theme-success-text mr-2"></i><span class="text-theme-success-text">✅ ${result.message || 'Email updated'}</span>`;
            elements.updateEmailResult.classList.remove('hidden');

            // Clear form
            if (elements.contributorSelect) elements.contributorSelect.value = '';
            if (elements.newEmailInput) elements.newEmailInput.value = '';
            if (elements.currentEmailText) elements.currentEmailText.textContent = '';
            if (elements.updateEmailBtn) elements.updateEmailBtn.disabled = true;

            // Refresh data
            fetchUsers();
            fetchContributors();
        } else {
            elements.updateEmailResult.className = 'mt-4 bg-theme-error-bg border border-theme-error-text rounded-lg p-4';
            elements.updateEmailResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ ${result.error || 'Failed to update email'}</span>`;
            elements.updateEmailResult.classList.remove('hidden');
        }
    } catch (error) {
        if (!elements.updateEmailResult) return;
        elements.updateEmailResult.className = 'mt-4 bg-theme-error-bg/10 border border-theme-error-text/30 rounded-lg p-4';
        elements.updateEmailResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ Error: ${error instanceof Error ? error.message : String(error)}</span>`;
        elements.updateEmailResult.classList.remove('hidden');
    }
}

// Render Unregistered Contributors
function renderUnregisteredContributors(): void {
    if (!elements.unregisteredList) return;

    const html = unregisteredContributors.map(contrib => {
        const email = contrib.email || 'No Email';
        const hasEmail = !!contrib.email;
        const fundsStr = contrib.funds ? contrib.funds.join(', ') : 'None';
        const contribution = contrib.total_contribution ? `$${parseFloat(String(contrib.total_contribution)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '$0.00';

        return `
            <div class="bg-dashboard-surface-alt rounded-lg p-4 flex items-center justify-between border border-border">
                <div class="flex-1">
                    <h4 class="font-semibold text-text-primary">${escapeHtmlForUsers(contrib.contributor)}</h4>
                    <p class="text-sm text-text-secondary">${escapeHtmlForUsers(email)}</p>
                    <p class="text-xs text-text-secondary mt-1">Funds: ${escapeHtmlForUsers(fundsStr)} | Contribution: ${contribution}</p>
                </div>
                <div>
                    ${hasEmail
                ? `<button class="send-invite-btn bg-accent text-white px-4 py-2 rounded-md hover:bg-accent-hover text-sm shadow-sm" 
                                 data-email="${escapeHtmlForUsers(contrib.email || '')}">
                            <i class="fas fa-envelope mr-1"></i>Send Invite
                          </button>`
                : `<span class="text-theme-warning-text text-sm">⚠️ Add email to invite</span>`}
                </div>
            </div>
        `;
    }).join('');

    elements.unregisteredList.innerHTML = html;

    // Attach event listeners
    document.querySelectorAll('.send-invite-btn').forEach(btn => {
        btn.addEventListener('click', (e: Event) => {
            const email = (e.currentTarget as HTMLElement).dataset.email;
            if (email) {
                sendInvite(email);
            }
        });
    });
}

// Update Contributor Selects for Access Management
function updateContributorSelects(): void {
    const options: string[] = ['<option value="">-- Select Contributor --</option>'];

    contributors.forEach(c => {
        const name = c.name || '';
        const email = c.email || 'No email';
        const display = `${name} (${email})`;
        options.push(`<option value="${escapeHtmlForUsers(email)}">${escapeHtmlForUsers(display)}</option>`);
    });

    const html = options.join('');
    if (elements.grantContributorSelect) {
        elements.grantContributorSelect.innerHTML = html;
    }
    if (elements.revokeContributorSelect) {
        elements.revokeContributorSelect.innerHTML = html;
    }
}

// Update User Selects
function updateUserSelects(): void {
    const options: string[] = ['<option value="">-- Select User --</option>'];

    users.forEach(u => {
        const email = u.email || '';
        if (email) {
            options.push(`<option value="${escapeHtmlForUsers(email)}">${escapeHtmlForUsers(email)}</option>`);
        }
    });

    const html = options.join('');
    if (elements.grantUserSelect) {
        elements.grantUserSelect.innerHTML = html;
    }
    if (elements.revokeUserSelect) {
        elements.revokeUserSelect.innerHTML = html;
    }
}

// Grant Contributor Access
async function handleGrantAccess(): Promise<void> {
    if (!elements.grantContributorSelect || !elements.grantUserSelect || !elements.grantAccessLevelSelect || !elements.grantAccessResult) return;

    const contributorEmail = elements.grantContributorSelect.value;
    const userEmail = elements.grantUserSelect.value;
    const accessLevel = elements.grantAccessLevelSelect.value;

    if (!contributorEmail || !userEmail) {
        showToast('Please select both contributor and user', 'warning');
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

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            elements.grantAccessResult.className = 'mt-4 bg-theme-success-bg border border-theme-success-text rounded-lg p-4';
            elements.grantAccessResult.innerHTML = `<i class="fas fa-check-circle text-theme-success-text mr-2"></i><span class="text-theme-success-text">✅ ${data.message || 'Access granted'}</span>`;
            elements.grantAccessResult.classList.remove('hidden');

            // Clear form
            elements.grantContributorSelect.value = '';
            elements.grantUserSelect.value = '';
            elements.grantAccessLevelSelect.value = 'viewer';

            // Refresh access records
            fetchAccessRecords();
        } else {
            elements.grantAccessResult.className = 'mt-4 bg-theme-error-bg border border-theme-error-text rounded-lg p-4';
            elements.grantAccessResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ ${data.error || data.message || 'Failed to grant access'}</span>`;
            elements.grantAccessResult.classList.remove('hidden');
        }
    } catch (error) {
        if (!elements.grantAccessResult) return;
        elements.grantAccessResult.className = 'mt-4 bg-theme-error-bg/10 border border-theme-error-text/30 rounded-lg p-4';
        elements.grantAccessResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ Error: ${error instanceof Error ? error.message : String(error)}</span>`;
        elements.grantAccessResult.classList.remove('hidden');
    }
}

// Render Access Table
function renderAccessTable(): void {
    if (!elements.accessTableBody) return;

    const rows = accessRecords.map(access => `
        <tr>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtmlForUsers(access.contributor)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtmlForUsers(access.contributor_email)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtmlForUsers(access.user_email)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtmlForUsers(access.user_name || '')}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">
                <span class="px-2 py-1 text-xs font-semibold rounded-full bg-theme-info-bg text-theme-info-text border border-theme-info-text/20">${escapeHtmlForUsers(access.access_level)}</span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${escapeHtmlForUsers(access.granted || '')}</td>
        </tr>
    `).join('');

    elements.accessTableBody.innerHTML = rows;
}

// Revoke Contributor Access
async function handleRevokeAccess(): Promise<void> {
    if (!elements.revokeContributorSelect || !elements.revokeUserSelect || !elements.revokeAccessResult) return;

    const contributorEmail = elements.revokeContributorSelect.value;
    const userEmail = elements.revokeUserSelect.value;

    if (!contributorEmail || !userEmail) {
        showToast('Please select both contributor and user', 'warning');
        return;
    }

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

        const data: ApiResponse = await response.json();

        if (response.ok && data.success) {
            elements.revokeAccessResult.className = 'mt-4 bg-theme-success-bg/10 border border-theme-success-text/30 rounded-lg p-4';
            elements.revokeAccessResult.innerHTML = `<i class="fas fa-check-circle text-theme-success-text mr-2"></i><span class="text-theme-success-text">✅ ${data.message || 'Access revoked'}</span>`;
            elements.revokeAccessResult.classList.remove('hidden');

            // Clear form
            elements.revokeContributorSelect.value = '';
            elements.revokeUserSelect.value = '';

            // Refresh access records
            fetchAccessRecords();
        } else {
            elements.revokeAccessResult.className = 'mt-4 bg-theme-error-bg/10 border border-theme-error-text/30 rounded-lg p-4';
            elements.revokeAccessResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ ${data.error || data.message || 'Failed to revoke access'}</span>`;
            elements.revokeAccessResult.classList.remove('hidden');
        }
    } catch (error) {
        if (!elements.revokeAccessResult) return;
        elements.revokeAccessResult.className = 'mt-4 bg-theme-error-bg/10 border border-theme-error-text/30 rounded-lg p-4';
        elements.revokeAccessResult.innerHTML = `<i class="fas fa-exclamation-circle text-theme-error-text mr-2"></i><span class="text-theme-error-text">❌ Error: ${error instanceof Error ? error.message : String(error)}</span>`;
        elements.revokeAccessResult.classList.remove('hidden');
    }
}

// Toast Notification System
function showToast(message: string, type: 'success' | 'error' | 'warning' | 'info' = 'success'): void {
    let container = document.getElementById('toast-container-users');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container-users';
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

    toast.className = `flex items-center w-full max-w-xs p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow-lg border-l-4 ${borderColor} transition-opacity duration-300 opacity-100 border border-border`;
    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal flex items-center gap-2">
            <span class="text-lg">${icon}</span>
            <span>${escapeHtmlForUsers(message)}</span>
        </div>
        <button type="button" class="ms-auto -mx-1.5 -my-1.5 bg-transparent text-text-secondary hover:text-text-primary rounded-lg focus:ring-2 focus:ring-accent p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8" aria-label="Close">
            <span class="sr-only">Close</span>
            <svg class="w-3 h-3" aria-true="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
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

// Helper Functions
function escapeHtmlForUsers(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
