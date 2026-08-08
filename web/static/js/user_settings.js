/**
 * User Settings Page JavaScript
 * Handles user information updates, appearance prefs, and password changes
 */

import { apiRequest, showToast } from './api.js';
import {
    loadPrefs,
    commitPrefs,
    normalizePrefs,
} from './ui_preferences.js';

class UserSettings {
    constructor() {
        this.initializeEventListeners();
        this.loadUserData();
        this.populateAppearanceForm(loadPrefs());
    }

    initializeEventListeners() {
        const userInfoForm = document.getElementById('userInfoForm');
        if (userInfoForm) {
            userInfoForm.addEventListener('submit', (e) => this.handleUserInfoUpdate(e));
        }

        const appearanceForm = document.getElementById('appearanceForm');
        if (appearanceForm) {
            appearanceForm.addEventListener('submit', (e) => this.handleAppearanceSave(e));
            // Live preview while adjusting (local only until Save).
            ['themeMode', 'accentPreset', 'densityPreset', 'mapStylePref'].forEach((id) => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('change', () => {
                        commitPrefs(this.readAppearanceForm(), {
                            persistLocal: true,
                            persistServer: false,
                        });
                    });
                }
            });
        }

        const passwordForm = document.getElementById('passwordChangeForm');
        if (passwordForm) {
            passwordForm.addEventListener('submit', (e) => this.handlePasswordChange(e));
        }

        const refreshBtn = document.getElementById('refreshUserDataBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadUserData());
        }

        const newPasswordInput = document.getElementById('newPassword');
        const confirmPasswordInput = document.getElementById('confirmPassword');

        if (newPasswordInput && confirmPasswordInput) {
            confirmPasswordInput.addEventListener('input', () => this.validatePasswordMatch());
            newPasswordInput.addEventListener('input', () => this.validatePasswordMatch());
        }
    }

    readAppearanceForm() {
        return normalizePrefs({
            theme_mode: document.getElementById('themeMode')?.value,
            accent: document.getElementById('accentPreset')?.value,
            density: document.getElementById('densityPreset')?.value,
            map_style: document.getElementById('mapStylePref')?.value,
        });
    }

    populateAppearanceForm(prefs) {
        const normalized = normalizePrefs(prefs);
        const themeMode = document.getElementById('themeMode');
        const accent = document.getElementById('accentPreset');
        const density = document.getElementById('densityPreset');
        const mapStyle = document.getElementById('mapStylePref');
        if (themeMode) themeMode.value = normalized.theme_mode;
        if (accent) accent.value = normalized.accent;
        if (density) density.value = normalized.density;
        if (mapStyle) mapStyle.value = normalized.map_style;
    }

    async loadUserData() {
        try {
            const userData = await apiRequest('/api/users/me', 'GET');
            this.populateUserData(userData);
        } catch (error) {
            showToast(`Failed to load user data: ${error.message}`, 'danger');
        }
    }

    populateUserData(userData) {
        const fullNameInput = document.getElementById('fullName');
        const emailInput = document.getElementById('email');

        if (fullNameInput) {
            fullNameInput.value = userData.full_name || '';
        }
        if (emailInput) {
            emailInput.value = userData.email || '';
        }

        if (userData.ui_preferences) {
            const prefs = commitPrefs(userData.ui_preferences, {
                persistLocal: true,
                persistServer: false,
            });
            this.populateAppearanceForm(prefs);
        }

        this.updateAccountStatusDisplay(userData);
    }

    updateAccountStatusDisplay(userData) {
        const statusBadge = document.querySelector('.badge');
        if (statusBadge) {
            if (userData.disabled) {
                statusBadge.className = 'badge bg-danger';
                statusBadge.textContent = 'Disabled';
            } else {
                statusBadge.className = 'badge bg-success';
                statusBadge.textContent = 'Active';
            }
        }
    }

    async handleAppearanceSave(event) {
        event.preventDefault();
        const saveBtn = document.getElementById('saveAppearanceBtn');
        const originalText = saveBtn ? saveBtn.innerHTML : '';

        try {
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Saving...';
            }

            const prefs = this.readAppearanceForm();
            commitPrefs(prefs, { persistLocal: true, persistServer: false });
            const updatedUser = await apiRequest('/api/users/me', 'PUT', {
                ui_preferences: prefs,
            });
            if (updatedUser?.ui_preferences) {
                this.populateAppearanceForm(updatedUser.ui_preferences);
                commitPrefs(updatedUser.ui_preferences, {
                    persistLocal: true,
                    persistServer: false,
                });
            }
            showToast('Appearance preferences saved.', 'success');
        } catch (error) {
            showToast(`Failed to save appearance: ${error.message}`, 'danger');
        } finally {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = originalText;
            }
        }
    }

    async handleUserInfoUpdate(event) {
        event.preventDefault();

        const updateBtn = document.getElementById('updateInfoBtn');
        const originalText = updateBtn.innerHTML;

        try {
            updateBtn.disabled = true;
            updateBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Updating...';

            const formData = {
                full_name: document.getElementById('fullName').value.trim() || null,
                email: document.getElementById('email').value.trim() || null,
            };

            const tokenInput = document.getElementById('sensorTrackerToken');
            const clearTokenCheckbox = document.getElementById('clearSensorTrackerToken');
            if (tokenInput && clearTokenCheckbox) {
                if (clearTokenCheckbox.checked) {
                    formData.sensor_tracker_token = null;
                } else {
                    const tokenValue = tokenInput.value.trim();
                    if (tokenValue) {
                        formData.sensor_tracker_token = tokenValue;
                    }
                }
            }

            const updatedUser = await apiRequest('/api/users/me', 'PUT', formData);
            this.populateUserData(updatedUser);
            if (tokenInput) tokenInput.value = '';
            if (clearTokenCheckbox) clearTokenCheckbox.checked = false;
            showToast('User information updated successfully!', 'success');
        } catch (error) {
            showToast(`Failed to update information: ${error.message}`, 'danger');
        } finally {
            updateBtn.disabled = false;
            updateBtn.innerHTML = originalText;
        }
    }

    async handlePasswordChange(event) {
        event.preventDefault();

        const changeBtn = document.getElementById('changePasswordBtn');
        const originalText = changeBtn.innerHTML;

        try {
            if (!this.validatePasswordMatch()) {
                return;
            }

            changeBtn.disabled = true;
            changeBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Changing...';

            const formData = {
                current_password: document.getElementById('currentPassword').value,
                new_password: document.getElementById('newPassword').value,
            };

            await apiRequest('/api/users/me/password', 'PUT', formData);

            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';

            showToast('Password changed successfully!', 'success');
        } catch (error) {
            showToast(`Failed to change password: ${error.message}`, 'danger');
        } finally {
            changeBtn.disabled = false;
            changeBtn.innerHTML = originalText;
        }
    }

    validatePasswordMatch() {
        const newPassword = document.getElementById('newPassword').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        const confirmInput = document.getElementById('confirmPassword');

        if (confirmPassword && newPassword !== confirmPassword) {
            confirmInput.setCustomValidity('Passwords do not match');
            confirmInput.classList.add('is-invalid');
            return false;
        }
        confirmInput.setCustomValidity('');
        confirmInput.classList.remove('is-invalid');
        return true;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new UserSettings();
});
