"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    window.valid = true;
    window.rows = [];
    window.tbody = document.getElementsByTagName("table")[0].children[0];
    window.adder_row = document.getElementById("adder-row");
    window.category_sum = document.getElementById("category-sum");
    window.account_sum = document.getElementById("account-sum");
    window.debt = document.getElementById("debt");

    document.getElementById('addrow').addEventListener('click', addRow);
    document.forms[0].addEventListener('submit', onSubmit);
    document.addEventListener("keydown", key);
    setUpRows();
});

function key(event) {
    if (event.key === "Escape") {
        // The default behavior of "esc" is to stop page load
        event.preventDefault();
        const back = new URLSearchParams(window.location.search).get('back');
        if (back) window.location.href = back;
    } else if (event.key === "Enter") {
        document.forms[0].submit();
    }
}

function findRow(input) {
    return rows.findIndex(
        ({ account, category, moved, transferred }) =>
            [account, category, moved, transferred].includes(input));
}

function setUpRow(tr) {
    var [account, category, transferred, moved] =
        Array.prototype.map.call(tr.children, n => n.children[0]);
    account.addEventListener('change', accountChanged);
    category.addEventListener('change', categoryChanged);
    transferred.addEventListener('input', amountChanged);
    transferred.addEventListener('blur', suggestAmounts);
    moved.addEventListener('input', amountChanged);
    moved.addEventListener('blur', suggestAmounts);
    const row = { account, category, moved, transferred };
    rows.push(row);
    return row;
}

function setUpRows() {
    const real_rows = Array.prototype.slice.call(tbody.children, 1, -1);
    for (var tr of real_rows) {
        setUpRow(tr);
    }
}

function addRow(event) {
    var tr = tbody.children[1].cloneNode(true);
    var { account, category, moved, transferred } = setUpRow(tr);
    const n = rows.length - 1;
    account.value = '';
    account.name = `tx-${n}-account`;
    category.value = '';
    category.name = `tx-${n}-category`;
    moved.value = '';
    moved.name = `tx-${n}-moved`;
    transferred.value = '';
    transferred.name = `tx-${n}-transferred`;
    tbody.insertBefore(tr, adder_row);
    document.forms[0].elements["tx-TOTAL_FORMS"].value = rows.length;
    if (event) {
        account.focus({ focusVisible: true });
    }
}

function unsuggest(element) {
    if (element.classList.contains('suggested')) {
        element.value = '';
        element.classList.remove('suggested');
    }
}
function suggest(element, value) {
    if (element.value === "" && document.activeElement !== element) {
        element.value = value;
        element.classList.add('suggested');
        return true;
    }
    return false;
}

function accountChanged({ target }) {
    // Enforce uniqueness
    if (target.value) {
        for (var { account } of rows) {
            if (account !== target && account.value === target.value) {
                account.value = "";
                accountChanged({ target: account });
            }
        }
    }

    var { category } = rows[findRow(target)];
    unsuggest(category);
    if (target.value in data.external)
        suggest(category, data.external[target.value]);
    suggestAmounts();
}

function categoryChanged({ target }) {
    target.classList.remove('suggested');

    // Enforce uniqueness
    if (target.value) {
        for (var { category } of rows) {
            if (category !== target && category.value === target.value) {
                category.value = "";
                categoryChanged({ target: category });
            }
        }
    }

    suggestAmounts();
}

function amountChanged({ target }) {
    target.classList.remove('suggested');
    suggestAmounts();
}

function suggestSums() {
    var to_category = [];
    var category_total = 0;
    var to_account = [];
    var account_total = 0;
    for (var { account, category, moved, transferred } of rows) {
        if (category.value) {
            if (moved.value) {
                category_total += +moved.value;
            } else {
                to_category.push(moved);
            }
        }
        if (account.value) {
            if (transferred.value) {
                account_total += +transferred.value;
            } else {
                to_account.push(transferred);
            }
        }
    }
    var result = false;
    if (!isNaN(-category_total) && to_category.length === 1) {
        result |= suggest(to_category[0], -category_total);
    }
    if (!isNaN(-account_total) && to_account.length === 1) {
        result |= suggest(to_account[0], -account_total);
    }
    return result;
}

function suggestRowConsistency(options) {
    var result = false;
    for (var { account, category, moved, transferred } of rows) {
        if (!account.value || !category.value) { continue; }
        if (options?.onlyExternal && account.value != category.value)
            continue;
        if (transferred.value && !isNaN(transferred.value))
            result |= suggest(moved, transferred.value);
        if (moved.value && !isNaN(moved.value))
            result |= suggest(transferred, moved.value);
    }
    return result;
}

function suggestAmounts() {
    for (var { moved, transferred } of rows) {
        unsuggest(moved);
        unsuggest(transferred);
    }
    // Try to make progress with each one, with this priority
    do {
        do {
            suggestSums();
        } while (suggestRowConsistency({ onlyExternal: true }));
    } while (suggestRowConsistency());

    checkValid();
}

function combineDebts(owed) {
    var amounts = Object.entries(owed).filter(o => o[1])
        .sort((a, b) => a[1] - b[1]);
    var result = [];
    var [from, amount] = ['', 0];
    while (amounts.length || amount) {
        if (!amount)
            [from, amount] = amounts.shift();
        if (!amounts.length)
            return [];  // Debts do not sum to zero
        const [to, other] = amounts.pop();
        const result_amount = Math.min(-amount, other);
        result.push([from, to, result_amount]);
        amount += other;
        if (amount > 0) {
            amounts.push([to, amount]);
            amount = 0;
        }
    }
    return result;
}

function checkValid() {
    var category_total = 0;
    var account_total = 0;
    var owed = {};
    for (var { account, category, moved, transferred } of rows) {
        if (category.value) {
            category_total += +moved.value;
            const budget = data.category_budget[category.value];
            if (!owed[budget]) owed[budget] = 0;
            owed[budget] += -moved.value;
        }
        if (account.value) {
            account_total += +transferred.value;
            const budget = data.account_budget[account.value];
            if (!owed[budget]) owed[budget] = 0;
            owed[budget] += +transferred.value;
        }
    }
    valid = true;
    if (category_total && !isNaN(category_total)) {
        category_sum.innerText = category_total + ' left to categorize';
        valid = false;
    } else {
        category_sum.innerText = '';
    }
    if (account_total && !isNaN(account_total)) {
        account_sum.innerText = account_total + ' left to account for';
        valid = false;
    } else {
        account_sum.innerText = '';
    }
    debt.innerText = combineDebts(owed)
        .map(([from, to, amount]) =>
            `${data.budget[to]} owes ${data.budget[from]} ${amount}`)
        .join(', ');

    document.getElementById("submit-button").disabled = !valid;
}

function onSubmit(event) {
    if (!valid) event.preventDefault();
}
