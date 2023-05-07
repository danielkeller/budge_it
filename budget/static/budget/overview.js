"use strict";

addEventListener("DOMContentLoaded", function () {
    let dragging = null;
    let findTarget;

    window.form = document.getElementById('form');
    window.table = document.getElementById('categories');
    const new_group_template =
        document.getElementById('new-group-t').content.firstElementChild;

    table.addEventListener('dragstart', (event) => {
        event.dataTransfer.dropEffect = "move";
        dragging = findDraggable(event.target);
        findTarget = isGroup(dragging) ? findGroup : findCategory;
    });
    table.addEventListener('dragover', (event) => {
        const element = findTarget(event.target);
        if (element) {
            event.preventDefault();
            element.classList.add('droppable');
            if (isCategory(dragging)) {
                const group = findGroup(event.target);
                if (group.lastElementChild.id !== 'new-group') {
                    group.appendChild(new_group_template.cloneNode(true));
                }
            }
        }
    });
    table.addEventListener('dragleave', (event) => {
        const element = findTarget(event.target);
        if (element && element !== findTarget(event.relatedTarget)) {
            element.classList.remove('droppable');
            if (isCategory(dragging)
                && findGroup(event.target) !== findGroup(event.relatedTarget)) {
                findGroup(event.target).lastElementChild.remove();
            }
        }
    });

    table.addEventListener('drop', (event) => {
        const element = findTarget(event.target);
        if (isGroup(dragging)) {
            reorderGroup(dragging, element);
        } else {
            reorder(dragging, element);
        }
    });

    formatCurrencies();
});

function findAncestor(element, predicate) {
    for (; element && (!element.tagName || !(predicate(element)));
        element = element.parentElement);
    return element;
}
function findDraggable(element) {
    return findAncestor(element, element => element.getAttribute('draggable'));
}
function isCategory(element) { return element.tagName === "TR"; }
function isGroup(element) { return element.tagName === "TBODY"; }
function findGroup(element) { return findAncestor(element, isGroup); }
function findCategory(element) { return findAncestor(element, isCategory); }

function reorder(source, target) {
    form.elements[`form-${source.dataset.form}-group`].value =
        target.id === 'new-group' ? "New Group" :
            target.parentElement.dataset.group;
    reorderImpl(new Set([source]), target);
}

function reorderGroup(source, target) {
    reorderImpl([...source.children].slice(1),
        target.children[target.children.length - 1]);
}

function reorderImpl(sources, target) {
    sources = new Set(sources);
    let j = 0;
    const trs = [...table.children].flatMap(tbody => [...tbody.children]);
    for (const tr of trs) {
        if (tr.dataset.form && !sources.has(tr))
            form.elements[`form-${tr.dataset.form}-order`].value = j++;
        if (tr === target)
            for (const source_tr of sources)
                form.elements[`form-${source_tr.dataset.form}-order`].value = j++;
    }
    form.submit();
}
