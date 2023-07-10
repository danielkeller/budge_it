from django.test import TestCase

from budget.models import *


def new_transaction():
    t = Transaction.objects.create(date=date(2023, 1, 1))
    return t, TransactionPart.objects.create(transaction=t)


class ModelTests(TestCase):
    def setUp(self):
        foouser = User.objects.create(username="foo")
        self.foo = Budget.objects.create(name="foo", budget_of=foouser)
        self.category = Category.objects.create(
            budget=self.foo, name="cat", currency='CHF')
        self.payee = Budget.objects.create(name="payee", payee_of=foouser)
        self.bar = Budget.objects.create(
            name="bar", budget_of=User.objects.create(username="bar"))
        self.bar.friends.add(self.foo)

    def test_budget(self):
        self.assertEqual(str(self.foo), "foo")
        self.assertRegex(self.foo.get_absolute_url(), str(self.foo.id))
        self.assertRegex(str(self.foo.budgetfriends_set.first()), "foo")
        self.assertEqual(self.foo.main_budget(), self.foo)
        self.assertEqual(self.payee.main_budget(), self.foo)
        self.assertFalse(self.foo.view_permission(AnonymousUser()))
        self.assertFalse(self.foo.view_permission(self.bar.budget_of))
        self.assertTrue(self.foo.view_permission(self.foo.budget_of))
        self.assertEqual(list(self.foo.visible_budgets()),
                         [self.payee, self.bar])
        disowned = Budget.objects.create(name="disowned")
        disowned.friends.add(self.foo)
        self.assertEqual(list(disowned.visible_budgets()), [self.foo])

    def test_account(self):
        self.assertRegex(self.category.get_absolute_url(),
                         str(self.category.id))
        self.assertRegex(str(self.category), "cat")
        self.assertRegex(str(self.foo.get_inbox(Category, 'CHF')), "foo")
        self.assertLess(self.category, self.foo.get_inbox(Category, 'CHF'))
        self.assertEqual(self.category.kind(), 'category')
        self.assertEqual(self.foo.get_inbox(Account, 'CHF').kind(), 'account')

    def test_simple_transaction(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: -10, payee: 10})
        self.assertEqual(t.flows()[0], {})
        self.assertEqual(t.flows()[1], {(self.category, payee): 10})
        t.set_entries(self.foo, {}, {self.category: -10, payee: 10})
        self.assertEqual(t.flows()[0], {})
        self.assertEqual(t.flows()[1], {(self.category, payee): 10})

    def test_wrong_transaction(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        with self.assertRaises(Exception):
            t.set_entries(self.foo, {}, {self.category: -10, payee: 7})

    def test_disconnected(self):
        _, t = new_transaction()
        self.foo.friends.clear()
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        with self.assertRaises(Exception):
            t.set_entries(self.foo, {}, {inbox: -10, bar: 10})

    def test_split_transaction1(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        self.assertEqual(t.entries()[1],
                         {self.category: -20, payee: 10, bar: 10})
        self.assertEqual(t.flows()[1], {(self.category, payee): 10,
                                        (self.category, inbox): 10,
                                        (inbox, bar): 10})

    def test_split_transaction2(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: 10, payee: -20, bar: 10})
        self.assertEqual(t.flows()[1], {(payee, inbox): 10,
                                        (inbox, bar): 10,
                                        (payee, self.category): 10})

    def test_split_transaction3(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: 10, payee: 10, bar: -20})
        self.assertEqual(t.flows()[1], {(bar, inbox): 20,
                                        (inbox, payee): 10,
                                        (inbox, self.category): 10})

    def test_other_side(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        foo = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        t_bar = Transaction.objects.get_for(self.bar, t.id)
        self.assertIsNotNone(t_bar)
        self.assertEqual(t_bar.parts.first().flows()[1], {(foo, bar): 10})

    def test_set_other_side(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        foo = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        t_bar = Transaction.objects.get_for(self.bar, t.id)
        t_bar.parts.first().set_entries(self.bar, {}, {bar: 20, foo: -20})
        self.assertEqual(t.flows()[1], {(self.category, payee): 10,
                                        (self.category, foo): 10,
                                        (foo, bar): 20})

    def test_get_for_none(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {self.category: -10, payee: 10})
        t_bar = Transaction.objects.get_for(self.bar, t.id)
        self.assertIsNone(t_bar)
        t_bar = Transaction.objects.get_for(self.bar, 1234)
        self.assertIsNone(t_bar)

    def test_payees_via_inbox(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_entries(self.foo, {}, {payee: -10, payee2: 10})
        self.assertEqual(t.entries()[1], {payee: -10, payee2: 10})
        self.assertEqual(t.flows()[1], {(payee, inbox): 10,
                                        (inbox, payee2): 10})

    def test_split_payees1(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        t.set_entries(self.foo, {}, {self.category: -20, payee: 5, payee2: 15})
        self.assertEqual(t.flows()[1], {(self.category, payee): 5,
                                        (self.category, payee2): 15})

    def test_split_payees2(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        t.set_entries(self.foo, {}, {self.category: -
                      10, payee: -5, payee2: 15})
        self.assertEqual(t.flows()[1], {(payee, self.category): 5,
                                        (self.category, payee2): 15})

    def test_tabluar1(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        out_account = self.foo.get_inbox(Account, 'CHF')
        in_account = self.payee.get_inbox(Account, 'CHF')
        t.set_entries(self.foo, {out_account: -10, in_account: 10},
                      {self.category: -10, payee: 10})
        self.assertEqual(t.tabular(), [
            TransactionPart.Row(out_account, self.category, -10, ''),
            TransactionPart.Row(in_account, payee, 10, '')])

    def test_tabluar2(self):
        _, t = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        out_account = self.foo.get_inbox(Account, 'CHF')
        in_account = self.payee.get_inbox(Account, 'CHF')
        t.set_entries(self.foo, {out_account: -10, in_account: 10},
                      {self.category: -20, payee: 20})
        self.assertEqual(t.tabular(), [
            TransactionPart.Row(None, self.category, -20, ''),
            TransactionPart.Row(out_account, None, -10, ''),
            TransactionPart.Row(in_account, None, 10, ''),
            TransactionPart.Row(None, payee, 20, '')])

    def test_auto_description1(self):
        t, tp = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        tp.set_entries(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        self.assertRegex(t.auto_description(self.category), "payee")
        self.assertRegex(t.auto_description(self.category), "bar")
        self.assertNotRegex(t.auto_description(self.category), "cat")

    def test_auto_description2(self):
        t, tp = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        tp.set_entries(self.foo, {}, {self.category: -
                                      20, payee: 10, bar: 15, inbox: -5})
        self.assertRegex(t.auto_description(self.category), "payee")
        self.assertRegex(t.auto_description(self.category), "bar")
        self.assertRegex(t.auto_description(self.category), "Inbox")
        self.assertNotRegex(t.auto_description(self.category), "cat")

    def test_auto_description3(self):
        t, tp = new_transaction()
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        tp.set_entries(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        account = Balance(self.foo, self.bar, 'CHF')
        self.assertRegex(t.auto_description(account), "payee")
        self.assertRegex(t.auto_description(account), "cat")
        self.assertNotRegex(t.auto_description(account), "Inbox")
        self.assertNotRegex(t.auto_description(account), "bar")


class FormTests(TestCase):
    pass  # todo
