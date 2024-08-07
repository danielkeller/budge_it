"use strict";

function ownAccount(value) {
    return value == data.budget || data.own_accounts.includes(+value);
}

class Editor extends HTMLElement {
    connectedCallback() {
        this.addEventListener('input', ({ target }) => {
            if (target.classList.contains('edit-currency')) checkValid();
        });
        this.addEventListener('account-change', ({ target }) => {
            'account' in target.dataset ? accountChanged(target) : categoryChanged(target);
        });
        this.addEventListener('currency-input', suggestAmounts);
        this.addEventListener('focusout', suggestAmounts);
        this.addEventListener('htmx:afterSwap', () => this.disableAmounts());
        setTimeout(() => {
            this.disableAmounts();
            for (const part of this.parts) {
                for (let { account, category } of part.rows) {
                    if (category.value === account.value && category.value != data.budget)
                        category.input.classList.add('suggested');
                }
            }
        }, 0);
        setTimeout(checkValid, 0);
    }
    get parts() { return this.querySelectorAll('edit-part'); }
    disableAmounts() {
        for (const part of this.parts) {
            for (let { account, category, moved, transferred } of part.rows) {
                transferred.input.disabled = !account.value;
                moved.input.disabled = !category.value;
            }
        }
    }
}
customElements.define("transaction-editor", Editor);

function editor() {
    return document.querySelector('transaction-editor');
}

class DateRepeat extends HTMLElement {
    connectedCallback() {
        this.addEventListener('change', ({ target }) => {
            if (target.name === 'tx-repeat')
                target.closest('span').dataset.value = target.value;
        })
    }
}
customElements.define("date-repeat", DateRepeat);

class EditPart extends HTMLElement {
    connectedCallback() {
        this.addEventListener('change', () => updateCurrency(this));
        setTimeout(() => {
            updateCurrency(this);
        }, 0);
    }
    get currencyInput() { return this.querySelector(`.part-currency`); }
    get rows() { return [...this.querySelectorAll('.edit-row')].map(editRow); }
}
customElements.define("edit-part", EditPart);

function getPart(element) {
    return element.closest('edit-part');
}
function getRow(element) {
    return editRow(element.closest('tr'));
}
function editRow(tr) {
    return {
        account: tr.children[0].children[0],
        category: tr.children[1].children[0],
        transferred: tr.children[2].children[0],
        moved: tr.children[3].children[0]
    };
}

class AccountSelect extends HTMLElement {
    connectedCallback() {
        this.addEventListener('input', this.#selectInput.bind(this));
        // This is a hack and also doesn't work very well (in FF at least).
        this.addEventListener('focusout', () => this.input.reportValidity());
        setTimeout(() => this.value = this.value, 0);
    }
    get #hidden() { return this.children[0]; }
    get #sigil() { return this.children[1]; }
    get input() { return this.children[2]; }
    get value() { return this.#hidden.value; }
    set value(value) {
        value = String(value);
        this.#hidden.value = value;
        // It could be more efficient to pass the ids in a separate dict.
        const option = this.#options.find(opt => opt.dataset.id === value);
        this.input.value = option ? option.dataset.name || option.value : value;
        this.#updateSigil();
    }
    get #options() { return Array.from(this.input.list?.options || []); }
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
    #selectInput() {
        accept(this);
        const option = this.#options.find(opt =>
            [opt.dataset.name, opt.value].includes(this.input.value));
        this.#hidden.value = option ? option.dataset.id : this.input.value;
        // Remove type emoji when selected
        if (option && this.input.value === option.value
            && option.dataset.name && option.dataset.name !== option.value) {
            this.input.value = option.dataset.name;
        }
        this.#updateSigil();
        this.dispatchEvent(new CustomEvent('account-change', { bubbles: true }));
    }
}
customElements.define("account-select", AccountSelect);

// TODO: Htmx can submit the values of custom elements
class CurrencyInput extends HTMLElement {
    connectedCallback() {
        this.addEventListener('input', this.#oninput.bind(this));
        whenContentIsReady(this, () => this.value = this.value);
    }
    static observedAttributes = ["currency"];
    attributeChangedCallback() {
        if (this.input && this.input.value)
            this.#hidden.value = parseCurrency(this.input.value, this.currency);
    }
    get #hidden() { return this.querySelectorAll("input")[0]; }
    get input() { return this.querySelectorAll("input")[1]; }
    get value() { return this.#hidden.value; }
    get currency() { return this.getAttribute('currency'); }
    set value(value) {
        this.#hidden.value = value;
        this.input.value = value ? formatCurrencyField(value, this.currency) : "";
    }
    #oninput() {
        accept(this);
        this.input.setCustomValidity('');
        if (this.input.value) {
            let parsed = parseCurrency(this.input.value, this.currency);
            if (isNaN(parsed))
                this.input.setCustomValidity("Not a valid number");
            this.#hidden.value = parsed;
        } else {
            this.#hidden.value = '';
        }
        this.dispatchEvent(new CustomEvent('currency-input', { bubbles: true }));
    }
}
customElements.define("currency-input", CurrencyInput);

function unsuggest(element) {
    if (element.input.classList.contains('suggested')) {
        element.value = '';
        element.input.classList.remove('suggested');
    }
}
function suggest(element, value) {
    if (element.value === "" && document.activeElement !== element.input) {
        element.value = value;
        element.input.classList.add('suggested');
        return true;
    }
    return false;
}
function accept(element) {
    element.input.classList.remove('suggested');
}

function accountChanged(target) {
    const { account, category, transferred } = getRow(target);
    unsuggest(category);
    if (!ownAccount(account.value) && !(account.value in data.friends)) {
        if (account.value in data.budgets) suggest(category, account.value);
        else if (account.value) suggest(category, account.value);
    }

    transferred.input.disabled = !account.value;
    if (transferred.input.disabled) transferred.value = '';
    categoryChanged(target);
}

function categoryChanged(target) {
    const { category, moved } = getRow(target);
    moved.input.disabled = !category.value;
    if (moved.input.disabled) moved.value = '';

    suggestAmounts();
}

function updateCurrency(part) {
    var fixed = false;
    for (const { account, category } of part.rows) {
        for (const selector of [account, category]) {
            fixed |= data.own_accounts.includes(+selector.value);
        }
    }
    const select = part.currencyInput;
    if (fixed) {
        select.setAttribute('readonly', '');
        for (const option of select.children) {
            option.disabled = !option.selected;
        }
    } else {
        select.removeAttribute('readonly');
        for (const option of select.children) {
            option.disabled = false;
        }
    }
    for (let input of part.querySelectorAll('currency-input'))
        input.setAttribute('currency', select.value);
    for (let input of part.querySelectorAll('account-select')) {
        if ('account' in input.dataset) {
            input.input.setAttribute('list', 'accounts-' + select.value);
        } else {
            input.input.setAttribute('list', 'categories-' + select.value);
        }
    }

    checkValid();
}

function suggestSums(options) {
    var result = false;
    for (const part of editor().parts) {
        var to_category = [];
        var from_categories = 0;
        var category_total = 0;
        var to_account = [];
        var account_total = 0;
        for (var { account, category, moved, transferred } of part.rows) {
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
    for (const part of editor().parts) {
        for (var { account, category, moved, transferred } of part.rows) {
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
    for (const part of editor().parts) {
        for (var { moved, transferred } of part.rows) {
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
    let valid = true;
    for (const part of editor().parts) {
        var category_total = 0;
        var account_total = 0;
        var owed = {};
        for (var { account, category, moved, transferred } of part.rows) {
            account_total = account_total + +transferred.value;
            let budget = ownAccount(account.value)
                ? data.budget : account.value;
            owed[budget] = (owed[budget] || 0) + +transferred.value;

            category_total = category_total + +moved.value;
            budget = ownAccount(category.value)
                ? data.budget : category.value;
            owed[budget] = (owed[budget] || 0) - +moved.value;
        }

        const currency = part.currencyInput.value;
        const category_sum = part.querySelector('.category-sum');
        if (category_total && isFinite(category_total)) {
            category_sum.innerText = formatCurrency(category_total, currency)
                + ' left to categorize';
            valid = false;
        } else {
            category_sum.innerText = '';
        }
        const account_sum = part.querySelector('.account-sum');
        if (account_total && isFinite(account_total)) {
            account_sum.innerText = formatCurrency(account_total, currency)
                + ' left to account for';
            valid = false;
        } else {
            account_sum.innerText = '';
        }
        const debt = part.querySelector('.debt');
        debt.innerText =
            combineDebts(owed)
                .map(([from, to, amount]) =>
                    `${data.budgets[to] || to} owes `
                    + `${data.budgets[from] || from} `
                    + `${formatCurrency(amount, currency)}`)
                .join(', ');
    }
    document.getElementById("submit-button").setCustomValidity(
        valid ? '' : 'Transaction does not sum to zero'
    );
}
