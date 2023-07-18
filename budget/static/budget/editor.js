"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    window.valid = true;
    window.parts = {};

    document.getElementById('cancel').addEventListener('click', cancel);
    document.forms[0].addEventListener('submit', onSubmit);
    document.addEventListener("keydown", key);
    checkValid();
});

htmx.onLoad(setUp);

function key(event) {
    if (event.key === "Escape") {
        // The default behavior of "esc" is to stop page load
        // event.preventDefault();
        // cancel();
    } else if (event.key === "Enter") {
        if (document.activeElement.type !== "button"
            && document.activeElement.type !== "submit"
            && document.activeElement.type !== "textarea")
            if (valid) document.forms[0].submit();
    }
}

function cancel() {
    let back = new URLSearchParams(window.location.search).get('back');
    if (back) {
        if (window.data.transaction) {
            back = `${back}?t=${window.data.transaction}`;
        }
        window.location.href = back;
    }
    else {
        history.back();
    }
}

function findRow(input) {
    for (const part of Object.values(window.parts)) {
        for (const row of part) {
            const { account, category, moved, transferred } = row;
            if ([account, category, moved, transferred].includes(input))
                return row;
        }
    }
}

function currencyInput(part) {
    return document.getElementById(`id_tx-${part}-currency`);
}

function getPart(element) {
    if (element.input)
        return element.input.closest('table').dataset.part;
    else
        return element.closest('table').dataset.part;
}

function ownAccount(value) {
    return value == data.budget || value in data.accounts;
}

// TODO: This could potentially do its thing in a more htmx-y way by setting
// values on elements and triggering events and it might avoid the windows.parts
// stuff.
// Specifically, one function can set up the event listeners and stuff, and
// another object can wrap these td's when they're returned from getRows(part)
class Selector {
    #visible; #hidden; #sigil; #oninput;
    constructor([hidden, sigil, visible], oninput) {
        this.#visible = visible;
        this.#sigil = sigil;
        this.#hidden = hidden;
        this.#oninput = oninput;
        visible.addEventListener('input', this.#selectInput.bind(this));
        // This is a hack and also doesn't work very well (in FF at least).
        visible.addEventListener('blur', () => visible.reportValidity());
        this.value = this.value;
    }
    get options() { return Array.from(this.#visible.list.options); }
    set value(value) {
        value = String(value);
        this.#hidden.value = value;
        const option = this.options.find(opt => opt.dataset.id === value);
        this.#visible.value = option ? option.dataset.name : value;
        this.#updateSigil();
    }
    get value() { return this.#hidden.value; }
    #updateSigil() {
        const sigil = ownAccount(this.value) ? '👤'
            : this.value in data.friends ? '👥'
                : null;
        if (sigil) {
            this.#sigil.classList.add('sigil');
            this.#sigil.textContent = sigil;
        } else {
            this.#sigil.classList.remove('sigil');
            this.#sigil.textContent = '';
        }
    }
    get input() { return this.#visible; }
    get classList() { return this.#visible.classList; }
    #selectInput() {
        accept(this);
        const option = this.options.find(opt =>
            [opt.dataset.name, opt.value].includes(this.#visible.value));
        this.#hidden.value = option ? option.dataset.id : this.#visible.value;
        if (option && this.#visible.value === option.value
            && option.dataset.name !== option.value) {
            this.#visible.value = option.dataset.name;
        }
        this.#updateSigil();
        this.#oninput({ target: this });
    }
}

class CurrencyInput {
    #hidden; #visible; #oninput;
    constructor([hidden, visible], oninput) {
        this.#hidden = hidden;
        this.#visible = visible;
        this.#oninput = oninput;
        this.#visible.addEventListener('input', this.#parse.bind(this));
        this.#visible.addEventListener('blur', () => this.#oninput({ target: this }));
        this.value = this.value;
    }
    set value(value) {
        this.#hidden.value = value;
        // Ugly!
        const currency = currencyInput(getPart(this.#hidden)).value;
        this.#visible.value = value ? formatCurrencyField(value, currency) : "";
    }
    get value() { return this.#hidden.value; }
    #parse() {
        accept(this);
        const currency = currencyInput(getPart(this.#hidden)).value;
        this.#hidden.value = this.#visible.value
            && parseCurrency(this.#visible.value, currency);
        this.#oninput({ target: this });
    }
    get classList() { return this.#visible.classList; }
    get input() { return this.#visible; }
}

function unsuggest(element) {
    if (element.classList.contains('suggested')) {
        element.value = '';
        element.classList.remove('suggested');
    }
}
function suggest(element, value) {
    if (element.value === "" && document.activeElement !== element.input) {
        element.value = value;
        element.classList.add('suggested');
        return true;
    }
    return false;
}
function accept(element) {
    element.classList.remove('suggested');
}

function setUpRow(tr) {
    var [account, category, transferred, moved] = Array.prototype.map.call(tr.children, n => n.children);
    account = new Selector(account, accountChanged);
    category = new Selector(category, categoryChanged);
    if (category.value === account.value && category.value != data.budget)
        category.classList.add('suggested');
    transferred = new CurrencyInput(transferred, suggestAmounts);
    moved = new CurrencyInput(moved, suggestAmounts);
    transferred.input.disabled = !account.value;
    moved.input.disabled = !category.value;
    const row = { account, category, moved, transferred };
    const part = getPart(tr);
    if (!(part in window.parts)) window.parts[part] = [];
    window.parts[part].push(row);
    updateCurrency(part);
}

function setUp(element) {
    if (element.classList.contains('edit-row')) {
        setUpRow(element);
    } else {
        for (const tr of element.querySelectorAll('.edit-row')) {
            setUpRow(tr);
        }
    }
    for (const input of element.querySelectorAll('.edit-currency')) {
        input.addEventListener('input', checkValid);
    }
}

function accountChanged({ target }) {
    const { category, transferred } = findRow(target);
    unsuggest(category);
    if (!ownAccount(target.value) && !(target.value in data.friends)) {
        if (target.value in data.budgets) suggest(category, target.value);
        else if (target.value) suggest(category, target.value);
    }

    transferred.input.disabled = !target.value;
    if (transferred.input.disabled) transferred.value = '';
    categoryChanged({ target: category });
}

function categoryChanged({ target }) {
    const { moved } = findRow(target);
    moved.input.disabled = !target.value;
    if (moved.input.disabled) moved.value = '';

    updateCurrency(getPart(target));
    suggestAmounts();
}

function updateCurrency(part) {
    var fixed = null;
    var fixed_account = '';
    for (const { account, category } of window.parts[part]) {
        for (const selector of [account, category]) {
            const account_currency = data.accounts[selector.value];
            if (fixed && account_currency
                && data.accounts[selector.value] != fixed) {
                // TODO: The list breaks reportValidity.
                // Create separate lists per currency
                selector.input.setCustomValidity(
                    `Currency of ${fixed_account} is ${fixed} but currency of `
                    + `${selector.input.value} is ${account_currency}`);
            } else {
                if (!fixed && account_currency) {
                    fixed = account_currency;
                    fixed_account = selector.input.value;
                }
                selector.input.setCustomValidity('');
            }
        }
    }
    const input = currencyInput(part);
    if (fixed) {
        input.value = fixed;
        input.setAttribute('readonly', '');
    } else {
        input.removeAttribute('readonly');
    }
}

function suggestSums(options) {
    var result = false;
    for (const rows of Object.values(window.parts)) {
        var to_category = [];
        var from_categories = 0;
        var category_total = 0;
        var to_account = [];
        var account_total = 0;
        for (var { account, category, moved, transferred } of rows) {
            if (category.value) {
                if (moved.value) {
                    from_categories++;
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
        const categoryCondition = options?.splitting
            ? to_category.length && from_categories
            : to_category.length === 1;
        if (category_total && isFinite(category_total) && categoryCondition) {
            const div = Math.floor(category_total / to_category.length);
            const rem = category_total - div * to_category.length;
            for (let i = 0; i < to_category.length; ++i)
                result |= suggest(to_category[i], -div - (i < rem));
        }
        if (account_total && isFinite(account_total) && to_account.length === 1) {
            result |= suggest(to_account[0], account_total ? -account_total : "");
        }

    }
    return result;
}

function suggestRowConsistency(options) {
    var result = false;
    for (const rows of Object.values(window.parts)) {
        for (var { account, category, moved, transferred } of rows) {
            if (!account.value || !category.value)
                continue;
            if (options?.onlyExternal && category.value !== account.value &&
                category.value !== `[${account.value}]`)
                continue;
            if (transferred.value && isFinite(+transferred.value))
                result |= suggest(moved, transferred.value);
            if (moved.value && isFinite(+moved.value))
                result |= suggest(transferred, moved.value);
        }
    }
    return result;
}

function suggestAmounts() {
    for (const rows of Object.values(window.parts)) {
        for (var { moved, transferred } of rows) {
            unsuggest(moved);
            unsuggest(transferred);
        }
    }
    // Try to make progress with each one, with this priority
    do {
        do {
            do {
                suggestSums();
            } while (suggestRowConsistency({ onlyExternal: true }));
        } while (suggestSums({ splitting: true }));
    } while (suggestRowConsistency());

    checkValid();
}

function combineDebts(owed) {
    var amounts = Object.entries(owed).filter(o => o[1])
        .sort((a, b) => a[1] - b[1]);
    var result = [];
    var [from, amount] = ['', 0];
    while (amounts.length || amount) {
        if (amount === 0)
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
    window.valid = true;
    for (const part of Object.keys(window.parts)) {
        const rows = window.parts[part];

        var category_total = 0;
        var account_total = 0;
        var owed = {};
        for (var { account, category, moved, transferred } of rows) {
            account_total = account_total + +transferred.value;
            let budget = ownAccount(account.value)
                ? data.budget : account.value;
            owed[budget] = (owed[budget] || 0) + +transferred.value;

            category_total = category_total + +moved.value;
            budget = ownAccount(category.value)
                ? data.budget : category.value;
            owed[budget] = (owed[budget] || 0) - +moved.value;
        }

        const currency = currencyInput(part).value;
        const category_sum = document.getElementById(`category-sum${part}`);
        if (category_total && isFinite(category_total)) {
            category_sum.innerText = formatCurrency(category_total, currency)
                + ' left to categorize';
            valid = false;
        } else {
            category_sum.innerText = '';
        }
        const account_sum = document.getElementById(`account-sum${part}`);
        if (account_total && isFinite(account_total)) {
            account_sum.innerText = formatCurrency(account_total, currency)
                + ' left to account for';
            valid = false;
        } else {
            account_sum.innerText = '';
        }
        const debt = document.getElementById(`debt${part}`);
        debt.innerText =
            combineDebts(owed)
                .map(([from, to, amount]) =>
                    `${data.budgets[to] || to} owes `
                    + `${data.budgets[from] || from} `
                    + `${formatCurrency(amount, currency)}`)
                .join(', ');
    }
    document.getElementById("submit-button").disabled = !valid;
}

function onSubmit(event) {
    if (!window.valid) event.preventDefault();
}
