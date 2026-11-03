import unittest
import tempfile
from pathlib import Path
from shapely.geometry import Polygon
from papercraft_nester.cutpath import bounded_folds,ExportFile

class FoldBounds(unittest.TestCase):
    def test_export_reader_applies_guard_without_changing_cut_outline(self):
        svg='''<svg xmlns="http://www.w3.org/2000/svg" data-contract="lowpoly-export/1"><g data-piece="piece-11-02" data-source-page="11" data-material="green"><path data-operation="cut" d="M 0,0 10,0 10,10 0,10 Z"/><path data-operation="score" data-fold="valley" d="M -5,2 -1,8"/><path data-operation="score" data-fold="valley" d="M 1,5 9,5"/></g></svg>'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.svg';path.write_text(svg)
            piece=next(iter(ExportFile(path).sheets.values())).pieces[0]
            self.assertEqual(piece.folds['valley'],[((1.,5.),(9.,5.))])
            self.assertEqual(piece.rings,[[(0.,0.),(10.,0.),(10.,10.),(0.,10.)]])

    def test_outside_fragment_is_dropped_and_valid_fold_unchanged(self):
        shape=Polygon([(0,0),(10,0),(10,10),(0,10)])
        inside=((1,5),(9,5)); boundary=((0,0),(10,0))
        self.assertEqual(bounded_folds([inside,boundary,((-5,2),(-1,8))],shape),[inside,boundary])

    def test_partial_fold_is_clipped_to_piece(self):
        shape=Polygon([(0,0),(10,0),(10,10),(0,10)])
        self.assertEqual(bounded_folds([((-5,5),(5,5))],shape),[((0.,5.),(5.,5.))])

    def test_concave_gap_and_cut_hole_are_not_scored(self):
        shape=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
        self.assertEqual(bounded_folds([((1,5),(9,5))],shape),[((1.,5.),(4.,5.)),((6.,5.),(9.,5.))])

if __name__=='__main__':unittest.main()
