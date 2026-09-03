from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from paperhere import synctex


class SyncTexTests(unittest.TestCase):
    def test_forward_parses_first_result(self) -> None:
        output = """\
SyncTeX result begin
Output:/tmp/paper.pdf
Page:2
x:101.25
y:202.5
h:99.0
v:210.0
W:42.0
H:11.5
Output:/tmp/paper.pdf
Page:3
x:1
y:2
SyncTeX result end
"""
        with patch.object(synctex, "_run", return_value=output) as run:
            result = synctex.forward(
                source=Path("/tmp/paper.tex"),
                line=17,
                column=4,
                pdf=Path("/tmp/paper.pdf"),
                cwd=Path("/tmp"),
            )

        self.assertEqual(result.page, 2)
        self.assertEqual(result.h, 99.0)
        self.assertEqual(result.v, 210.0)
        self.assertEqual(result.width, 42.0)
        self.assertEqual(result.height, 11.5)
        self.assertIn("17:4:/tmp/paper.tex", run.call_args.args[0])

    def test_inverse_resolves_relative_source_and_normalizes_column(self) -> None:
        output = """\
SyncTeX result begin
Output:/work/paper.pdf
Input:./chapters/intro.tex
Line:31
Column:-1
SyncTeX result end
"""
        with patch.object(synctex, "_run", return_value=output):
            result = synctex.inverse(
                pdf=Path("/work/paper.pdf"),
                page=1,
                x=100,
                y=120,
                cwd=Path("/work"),
            )

        self.assertEqual(result.path, Path("/work/chapters/intro.tex"))
        self.assertEqual(result.line, 31)
        self.assertEqual(result.column, 0)

    def test_missing_result_raises_clear_error(self) -> None:
        with patch.object(synctex, "_run", return_value="SyncTeX result begin\n"):
            with self.assertRaisesRegex(synctex.SyncTexError, "No location"):
                synctex.forward(
                    source=Path("/tmp/a.tex"),
                    line=1,
                    column=1,
                    pdf=Path("/tmp/a.pdf"),
                    cwd=Path("/tmp"),
                )


if __name__ == "__main__":
    unittest.main()
