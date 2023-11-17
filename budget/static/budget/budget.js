"use strict";

class BudgetForm extends HTMLElement {
    connectedCallback() {
        this.addEventListener('currency-input', ({ target }) => {
            updateFinal(target);

            let total = 0;
            const currency = target.getAttribute('currency');
            const selector = `[data-budget-category][currency=${currency}]`;
            for (const category of this.querySelectorAll(selector)) {
                total += +category.value;
            }
            const inbox = this.querySelector(`[data-budget-inbox][currency=${currency}]`);
            inbox.value = -total || "";
            updateFinal(inbox)
        });
    }
}
customElements.define("budget-form", BudgetForm);

function updateFinal(input) {
    const final = input.closest('tr').querySelector('[data-total]');
    final.value = +final.dataset.total + (+input.value || 0);
}

class DatePicker extends HTMLElement {
    connectedCallback() {
        this.addEventListener('change', () => {
            const year = this.querySelector('form').year.value;
            for (const link of this.querySelectorAll(".months>a")) {
                const href = link.getAttribute('href').replace(/\d{4}/, year);
                if (href === window.location.pathname) {
                    link.classList.add('current');
                } else {
                    link.classList.remove('current');
                }
                link.setAttribute('href', href);
            }
        });
    }
}
customElements.define("date-picker", DatePicker);
