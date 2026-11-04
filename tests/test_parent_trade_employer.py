import unittest
from public_recruiting import _binding


class ParentTradeEmployer(unittest.TestCase):
    data={'organisasjonsnummer':'911605287','navn':'ACME NORGE AS'}
    unit={'overordnetEnhet':'911605287','organisasjonsnummer':'974287005','navn':'EXAMPLE TRADE OSLO'}

    def test_literal_parent_number_and_exact_registered_workplace_name(self):
        proof=_binding('911605287','Example Trade Oslo',self.data,[self.unit])
        self.assertEqual(proof['target_organisation_number'],'911605287')
        self.assertEqual(proof['published_organisation_number'],'911605287')
        self.assertEqual(proof['registered_trade_unit_number'],'974287005')

    def test_another_legal_employer_cannot_borrow_the_brand_or_parent(self):
        self.assertIsNone(_binding('913884213','Example Trade Oslo',self.data,[self.unit]))
        self.assertIsNone(_binding('911605287','Example Trade Oslo',self.data,[{**self.unit,'overordnetEnhet':'913884213'}]))

    def test_unregistered_shortened_or_other_branch_name_is_insufficient(self):
        for name in ['Example Trade','Example Trade Bergen','Example Trade Oslo AS','ACME GROUP']:
            with self.subTest(name=name):self.assertIsNone(_binding('911605287',name,self.data,[self.unit]))

    def test_empty_or_invalid_registry_workplace_number_is_not_a_trade_anchor(self):
        for number in ['',None,'123456789']:
            with self.subTest(number=number):self.assertIsNone(_binding('911605287','Example Trade Oslo',self.data,[{**self.unit,'organisasjonsnummer':number}]))

    def test_name_alone_or_child_number_with_a_different_name_is_not_enough(self):
        self.assertIsNone(_binding(None,'Example Trade Oslo',self.data,[self.unit]))
        self.assertIsNone(_binding('974287005','Unknown workplace',self.data,[self.unit]))
