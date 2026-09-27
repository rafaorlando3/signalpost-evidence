import unittest
from insights import synthesize


def claim(field, value, state='available'):
    return dict(field=field, value=value, availability=state, evidence_ids=['e-'+field],
                reporting_period={'fraDato':'2025-01-01','tilDato':'2025-12-31'})


def year(y, revenue, currency='NOK'):
    return dict(period={'fraDato':f'{y}-01-01','tilDato':f'{y}-12-31'}, revenue=revenue, currency=currency)


class Insights(unittest.TestCase):
    def calculations(self, history):
        return [s for s in synthesize([claim('financials.history',history)]) if s['kind']=='calculation']

    def test_growth_uses_consecutive_same_currency_years_and_links_evidence(self):
        s = self.calculations([year(2025,125),year(2024,100)])[0]
        self.assertEqual(s['calculation']['percent'],25)
        self.assertEqual(s['evidence_ids'],['e-financials.history'])
        self.assertIn('not a forecast',s['text'])

    def test_refuses_currency_changes_partial_years_and_missing_data(self):
        partial = year(2025,125); partial['period']['fraDato']='2025-07-01'
        cases = [[year(2024,100),year(2025,125,'EUR')],
                 [year(2024,100),partial], [year(2024,100),year(2026,125)],
                 [year(2025,100),year(2025,125)], [year(2024,None),year(2025,125)],
                 [year(2024,0),year(2025,125)], [year(2024,-100),year(2025,125)],
                 [year(2024,True),year(2025,125)], [year(2024,100),year(2025,float('inf'))]]
        for history in cases:
            with self.subTest(history=history): self.assertEqual(self.calculations(history),[])

    def test_zero_revenue_preserved_not_missing(self):
        statements=synthesize([claim('financials.revenue',0),claim('financials.currency','NOK')])
        self.assertIn('0 NOK',statements[0]['text'])
        self.assertNotIn('limitation',[s['kind'] for s in statements])
        self.assertEqual(self.calculations([year(2024,100),year(2025,0)])[0]['calculation']['percent'],-100)

    def test_failure_and_ambiguity_never_become_absence_claims(self):
        claims=[claim('financials.revenue',None,'failed'),claim('website.verified_url',None,'ambiguous')]
        statements=synthesize(claims)
        self.assertEqual({s['availability'] for s in statements},{'failed','ambiguous'})
        self.assertTrue(all('not zero or proof of absence' in s['text'] for s in statements))
        self.assertTrue(all(s['kind']=='limitation' for s in statements))

    def test_refresh_explanation_points_to_new_evidence(self):
        changes=[{'field':'employees','new_evidence_ids':['new']}]
        s=synthesize([claim('employees',2)],changes)[-1]
        self.assertEqual(s['kind'],'refresh');self.assertEqual(s['evidence_ids'],['new'])

if __name__=='__main__':unittest.main()
