from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class NvimRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("nvim"), "Neovim is not installed")
    def test_viewer_uses_configured_pdf_without_compiler_output(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        backend = repository / "paperhere/nvim/autoload/vimtex/view/paperhere.vim"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            autoload = root / "autoload/vimtex/view"
            autoload.mkdir(parents=True)
            (autoload / "_template.vim").write_text(
                "let s:viewer = {}\n"
                "function! s:viewer.init() dict abort\n"
                "  let l:viewer = deepcopy(self)\n"
                "  unlet l:viewer.init\n"
                "  return l:viewer\n"
                "endfunction\n"
                "function! vimtex#view#_template#new(viewer) abort\n"
                "  return extend(deepcopy(s:viewer), a:viewer)\n"
                "endfunction\n"
            )
            result_path = root / "result"
            pdf = root / "build/paper.pdf"
            script = root / "test.vim"
            script.write_text(
                "set runtimepath^=" + str(root) + "\n"
                "execute 'source ' . fnameescape($PAPERHERE_TEST_BACKEND)\n"
                "let g:paperhere_test_viewer = vimtex#view#paperhere#new()\n"
                "call writefile([g:paperhere_test_viewer.out()], $PAPERHERE_TEST_RESULT)\n"
                "qa!\n"
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PAPERHERE_PDF": str(pdf),
                    "PAPERHERE_TEST_BACKEND": str(backend),
                    "PAPERHERE_TEST_RESULT": str(result_path),
                }
            )

            completed = subprocess.run(
                ["nvim", "--headless", "-u", "NONE", "-S", str(script)],
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(
                result_path.is_file(),
                f"Neovim did not write the result:\n{completed.stdout}{completed.stderr}",
            )
            self.assertEqual(result_path.read_text().strip(), str(pdf))


if __name__ == "__main__":
    unittest.main()
