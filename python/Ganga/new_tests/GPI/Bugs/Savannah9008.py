from __future__ import absolute_import

from ..GangaUnitTest import GangaUnitTest


class Savannah9008(GangaUnitTest):
    def Savannah9008(self):
        from Ganga.GPI import TestApplication, File

        dv1 = TestApplication()
        dv1.optsfile = File('x')

        dv2 = TestApplication()
        dv2.optsfile = 'x'

        self.assertEqual(dv1.optsfile.name, dv2.optsfile.name)
        self.assertEqual(dv1, dv2)