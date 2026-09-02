/**
 * Mobile navbar: body scroll lock, padding sync, and backdrop dismiss while collapse menu is open.
 */
function initMobileNavbar() {
    const collapse = document.getElementById('bannerNavCollapse');
    const navbar = document.querySelector('.gbs-navbar:not(.gbs-navbar--simple)');
    if (!collapse || !navbar) return;

    let collapseInstance = null;

    function getCollapseInstance() {
        if (!collapseInstance) {
            collapseInstance = bootstrap.Collapse.getOrCreateInstance(collapse, { toggle: false });
        }
        return collapseInstance;
    }

    function syncBodyPadding() {
        document.body.style.paddingTop = `${navbar.offsetHeight}px`;
    }

    function restoreBodyPadding() {
        document.body.style.paddingTop = '';
    }

    collapse.addEventListener('show.bs.collapse', () => {
        navbar.classList.add('menu-open');
        document.body.style.overflow = 'hidden';
    });

    collapse.addEventListener('shown.bs.collapse', () => {
        syncBodyPadding();
    });

    collapse.addEventListener('hidden.bs.collapse', () => {
        navbar.classList.remove('menu-open');
        document.body.style.overflow = '';
        restoreBodyPadding();
    });

    document.addEventListener('click', (event) => {
        if (!navbar.classList.contains('menu-open')) return;
        if (navbar.contains(event.target)) return;
        getCollapseInstance().hide();
    });
}

document.addEventListener('DOMContentLoaded', initMobileNavbar);
