"use strict";

// This is broken by default
document.addEventListener('mouseover', ({ target }) => {
    if (target.tagName === 'INPUT') {
        for (let el = target; el; el = el.parentElement)
            if (el.getAttribute('draggable') === 'true')
                el.draggable = false;
    }
});
document.addEventListener('mouseout', ({ target }) => {
    if (target.tagName === 'INPUT') {
        for (let el = target; el; el = el.parentElement)
            if (el.getAttribute('draggable') === 'false')
                el.draggable = true;
    }
});
document.addEventListener('input', ({ target }) => {
    if (target.classList.contains('groupname')) {
        for (const item of target.closest('tbody').querySelectorAll('.group'))
            item.value = target.value;
    }
});