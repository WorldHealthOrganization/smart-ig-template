document.addEventListener("DOMContentLoaded", function () {
    // Initialize theme on page load
    initTheme();
});

function initTheme() {
    // Get saved theme or default to light
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    applyTheme(newTheme);
    localStorage.setItem('theme', newTheme);
}

function applyTheme(theme) {
    const root = document.documentElement;
    const themeIcon = document.getElementById('theme-icon');
    const themeText = document.getElementById('theme-text');
    
    if (theme === 'dark') {
        root.setAttribute('data-theme', 'dark');
        if (themeIcon) {
            themeIcon.className = 'fas fa-sun';
        }
        if (themeText) {
            themeText.textContent = 'Light';
        }
    } else {
        root.removeAttribute('data-theme');
        if (themeIcon) {
            themeIcon.className = 'fas fa-moon';
        }
        if (themeText) {
            themeText.textContent = 'Dark';
        }
    }
}