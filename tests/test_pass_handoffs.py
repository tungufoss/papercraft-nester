import itertools
import unittest
import tempfile
from pathlib import Path
import xml.etree.ElementTree as E
from papercraft_nester.cutpath import ExportFile, Piece, Sheet, path_travel
from papercraft_nester.route import HeuristicRouter


class RecordingRouter(HeuristicRouter):
    def __init__(self):
        self.starts = []

    def solve(self, jobs, home):
        self.starts.append(home)
        return super().solve(jobs, home)


class PassHandoffs(unittest.TestCase):
    def test_cricut_layer_order_reversed_without_changing_route(self):
        piece=Piece('p','red',[[(0,0),(10,0),(10,10),(0,10)]],
                    {'mountain':[((1,2),(9,2))],'valley':[((1,5),(9,5))]},
                    [[[(2,3),(4,3)]]])
        sheet=Sheet(1,'red',(0,0),(100,150),[piece]).plan(HeuristicRouter(),.35)
        doc=ExportFile.__new__(ExportFile);doc.sheets={1:sheet}
        with tempfile.TemporaryDirectory() as folder:
            paths=doc.write_sheets(Path(folder),'test')
            combined=Path(folder)/'combined.svg';doc.write_cricut(combined)
            for path in [*paths,combined]:
                ops=[n.get('data-operation') for n in E.parse(path).iter() if n.get('data-operation')]
                self.assertEqual(ops,['cut','valley','mountain','draw'])
        self.assertEqual([p.kind for p in sheet.passes],['draw','mountain','valley','cut'])

    def test_all_missing_layer_combinations(self):
        for draw, mountain, valley in itertools.product((False, True), repeat=3):
            with self.subTest(draw=draw, mountain=mountain, valley=valley):
                piece = Piece('p', 'red', [[(15, 25), (25, 25), (25, 35), (15, 35)]],
                              {'mountain': [((16, 26), (24, 26))] if mountain else [],
                               'valley': [((16, 30), (24, 30))] if valley else []},
                              [[[(17, 27), (19, 29)], [(20, 29), (21, 27)]]] if draw else [])
                sheet = Sheet(1, 'red', (10, 20), (100, 150), [piece])
                router = RecordingRouter()
                sheet.plan(router, .35, stay_down=10)
                self.assertEqual([p.kind for p in sheet.passes], ['draw', 'mountain', 'valley', 'cut'])
                pos = (60, 20)
                for p, start in zip(sheet.passes, router.starts):
                    self.assertEqual(start, pos)
                    self.assertEqual(p.start, pos)
                    self.assertAlmostEqual(p.travel, path_travel(p.lines, pos))
                    if p.strokes:
                        pos = p.strokes[-1][1][-1]


if __name__ == '__main__':
    unittest.main()
