from django.test import TestCase

from budget.models import *


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

    def test_simple_transaction(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: -10, payee: 10})
        self.assertEqual(t.parts()[0], {})
        self.assertEqual(t.parts()[1], {(self.category, payee): 10})
        t.set_parts(self.foo, {}, {self.category: -10, payee: 10})
        self.assertEqual(t.parts()[0], {})
        self.assertEqual(t.parts()[1], {(self.category, payee): 10})

    def test_wring_transaction(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        with self.assertRaises(Exception):
            t.set_parts(self.foo, {}, {self.category: -10, payee: 7})

    def test_split_transaction1(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        self.assertEqual(t.entries()[1],
                         {self.category: -20, payee: 10, bar: 10})
        self.assertEqual(t.parts()[1], {(self.category, payee): 10,
                                        (self.category, inbox): 10,
                                        (inbox, bar): 10})

    def test_split_transaction2(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: 10, payee: -20, bar: 10})
        self.assertEqual(t.parts()[1], {(payee, inbox): 10,
                                        (inbox, bar): 10,
                                        (payee, self.category): 10})

    def test_split_transaction3(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: 10, payee: 10, bar: -20})
        self.assertEqual(t.parts()[1], {(bar, inbox): 20,
                                        (inbox, payee): 10,
                                        (inbox, self.category): 10})

    def test_other_side(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        foo = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        t_bar = Transaction.objects.get_for(self.bar, t.id)
        self.assertIsNotNone(t_bar)
        self.assertEqual(t_bar.parts()[1], {(foo, bar): 10})

    def test_set_other_side(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        bar = self.bar.get_inbox(Category, 'CHF')
        foo = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {self.category: -20, payee: 10, bar: 10})
        t_bar = Transaction.objects.get_for(self.bar, t.id)
        t_bar.set_parts(self.bar, {}, {bar: 20, foo: -20})
        self.assertEqual(t.parts()[1], {(self.category, payee): 10,
                                        (self.category, foo): 10,
                                        (foo, bar): 20})

    def test_payees_via_inbox(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        inbox = self.foo.get_inbox(Category, 'CHF')
        t.set_parts(self.foo, {}, {payee: -10, payee2: 10})
        self.assertEqual(t.entries()[1], {payee: -10, payee2: 10})
        self.assertEqual(t.parts()[1], {(payee, inbox): 10,
                                        (inbox, payee2): 10})

    def test_split_payees1(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        t.set_parts(self.foo, {}, {self.category: -20, payee: 5, payee2: 15})
        self.assertEqual(t.parts()[1], {(self.category, payee): 5,
                                        (self.category, payee2): 15})

    def test_split_payees2(self):
        t = Transaction.objects.create(date=date(2023, 1, 1))
        payee = self.payee.get_inbox(Category, 'CHF')
        payee2 = (Budget.objects
                  .create(name="payee2", payee_of_id=self.foo.owner())
                  .get_inbox(Category, 'CHF'))
        t.set_parts(self.foo, {}, {self.category: -10, payee: -5, payee2: 15})
        self.assertEqual(t.parts()[1], {(payee, self.category): 5,
                                        (self.category, payee2): 15})
