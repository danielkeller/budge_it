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

const new_group_template =
    document.getElementById('new-group-t').content.firstElementChild;
let findTarget = null;
let dragging = null;
function isGroup(element) { return 'group' in element.dataset; }
function isAccount(element) { return 'account' in element.dataset; }
function isCategory(element) { return !isAccount(element) && !isGroup(element); }
function findGroup(element) { return element.closest('[data-group]'); }
function findCategory(element) { return element.closest('[data-group]>tr'); }
function findAccount(element) { return element.closest('[data-account]'); }

document.addEventListener('dragstart', (event) => {
    dragging = event.target.closest('[draggable=true]');
    dragging.classList.add('dragging');
    findTarget = isGroup(dragging) ? findGroup : isAccount(dragging) ? findAccount : findCategory;
});
document.addEventListener('dragend', () => {
    dragging.classList.remove('dragging');
});
document.addEventListener('dragover', (event) => {
    const element = findTarget(event.target);
    if (element) {
        event.preventDefault();
        // TODO: This doesn't really work on 'tbody'
        element.classList.add('droppable');
        if (isCategory(dragging)) {
            const group = findGroup(event.target);
            if (group.lastElementChild.id !== 'new-group') {
                group.appendChild(new_group_template.cloneNode(true));
            }
        }
    }
});
document.addEventListener('dragleave', (event) => {
    const current = document.querySelector('.droppable');
    const entered = event.relatedTarget && findTarget(event.relatedTarget);
    // Don't flicker when we go between rows
    if (current && ((entered && entered !== current)
        || !event.relatedTarget?.closest('table')
    )) {
        current.classList.remove('droppable');
        if (isCategory(dragging)
            && findGroup(current) !== findGroup(event.relatedTarget)) {
            findGroup(current).lastElementChild.remove();
        }
    }
});
document.addEventListener('drop', (event) => {
    const element = findTarget(event.target);
    if (isGroup(dragging)) {
        reorder(dragging, element.lastElementChild);
    } else if (isAccount(dragging)) {
        reorder(dragging, element);
    } else {
        const targetGroup = element.querySelector('.group,.groupname');
        dragging.querySelector('.group').value =
            targetGroup ? targetGroup.value : "New Group";
        reorder(dragging, element);
    }
});

function reorder(source, target) {
    const sources = new Set(source.querySelectorAll('.order'));
    target = target.querySelector('.order');
    let i = 0;
    for (const input of document.querySelectorAll('.order')) {
        if (input.tagName === 'INPUT' && !sources.has(input))
            input.value = i++;
        if (input === target)
            for (const source_input of sources)
                source_input.value = i++;
    }
    form.submit();
}