import unittest
from agent import foreign_group_description


class ForeignDescriptionScope(unittest.TestCase):
    def test_parent_group_metadata_is_not_the_local_country_company(self):
        data={'navn':'EXAMPLE GROUP NORWAY AS'}
        self.assertTrue(foreign_group_description(data,'Die Example Group ist weltweit tätig und besitzt mehrere Marken.'))
        self.assertTrue(foreign_group_description(data,'Die Example Gruppe besteht aus mehreren Unternehmen.'))

    def test_full_local_company_subject_is_retained(self):
        data={'navn':'EXAMPLE GROUP NORWAY AS'}
        self.assertFalse(foreign_group_description(data,'Die Example Group Norway ist unser norwegisches Unternehmen.'))
        self.assertFalse(foreign_group_description(data,'Example Group Norway liefert Produkte in Norwegen.'))

    def test_actual_parent_entity_and_later_group_mentions_are_not_vetoed(self):
        self.assertFalse(foreign_group_description({'navn':'EXAMPLE GROUP AS'},'Die Example Group ist weltweit tätig.'))
        self.assertFalse(foreign_group_description({'navn':'LOCAL AS'},'Local AS ist in Oslo. Die Example Group ist unser Partner.'))
