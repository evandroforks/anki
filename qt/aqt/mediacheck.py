# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import itertools
import time
from concurrent.futures import Future
from typing import Iterable, List, Optional, TypeVar

import aqt
from anki import hooks
from anki.rsbackend import (
    Interrupted,
    MediaCheckOutput,
    Progress,
    ProgressKind,
    StringsGroup,
)
from aqt.qt import *
from aqt.utils import askUser, restoreGeom, saveGeom, showText, tooltip, tr

T = TypeVar("T")


def chunked_list(l: Iterable[T], n: int) -> Iterable[List[T]]:
    l = iter(l)
    while True:
        res = list(itertools.islice(l, n))
        if not res:
            return
        yield res


def check_media_db(mw: aqt.AnkiQt) -> None:
    c = MediaChecker(mw)
    c.check()


class MediaChecker:
    progress_dialog: Optional[aqt.progress.ProgressDialog]

    def __init__(self, mw: aqt.AnkiQt) -> None:
        self.mw = mw

    def check(self) -> None:
        self.progress_dialog = self.mw.progress.start()
        hooks.bg_thread_progress_callback.append(self._on_progress)
        self.mw.col.close()
        self.mw.taskman.run_in_background(self._check, self._on_finished)

    def _on_progress(self, proceed: bool, progress: Progress) -> bool:
        if progress.kind != ProgressKind.MediaCheck:
            return proceed

        if self.progress_dialog.wantCancel:
            return False

        self.mw.taskman.run_on_main(lambda: self.mw.progress.update(progress.val))
        return True

    def _check(self) -> MediaCheckOutput:
        "Run the check on a background thread."
        return self.mw.col.media.check()

    def _on_finished(self, future: Future) -> None:
        hooks.bg_thread_progress_callback.remove(self._on_progress)
        self.mw.progress.finish()
        self.progress_dialog = None
        self.mw.col.reopen()

        exc = future.exception()
        if isinstance(exc, Interrupted):
            return

        output: MediaCheckOutput = future.result()
        report = output.report

        # show report and offer to delete
        diag = QDialog(self.mw)
        diag.setWindowTitle("Anki")
        layout = QVBoxLayout(diag)
        diag.setLayout(layout)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(report)
        layout.addWidget(text)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(box)

        if output.unused:
            b = QPushButton(tr(StringsGroup.MEDIA_CHECK, "delete-unused"))
            b.setAutoDefault(False)
            box.addButton(b, QDialogButtonBox.RejectRole)
            b.clicked.connect(lambda c: self._on_trash_files(output.unused))  # type: ignore

        if output.missing:
            if any(map(lambda x: x.startswith("latex-"), output.missing)):
                b = QPushButton(tr(StringsGroup.MEDIA_CHECK, "render-latex"))
                b.setAutoDefault(False)
                box.addButton(b, QDialogButtonBox.RejectRole)
                b.clicked.connect(self._on_render_latex)  # type: ignore

        box.rejected.connect(diag.reject)  # type: ignore
        diag.setMinimumHeight(400)
        diag.setMinimumWidth(500)
        restoreGeom(diag, "checkmediadb")
        diag.exec_()
        saveGeom(diag, "checkmediadb")

    def _on_render_latex(self):
        self.progress_dialog = self.mw.progress.start()
        try:
            out = self.mw.col.media.render_all_latex(self._on_render_latex_progress)
            if self.progress_dialog.wantCancel:
                return
        finally:
            self.mw.progress.finish()
            self.progress_dialog = None

        if out is not None:
            nid, err = out
            browser = aqt.dialogs.open("Browser", self.mw)
            browser.form.searchEdit.lineEdit().setText("nid:%d" % nid)
            browser.onSearchActivated()
            showText(err, type="html")
        else:
            tooltip(tr(StringsGroup.MEDIA_CHECK, "all-latex-rendered"))

    def _on_render_latex_progress(self, count: int) -> bool:
        if self.progress_dialog.wantCancel:
            return False

        self.mw.progress.update(tr(StringsGroup.MEDIA_CHECK, "checked", count=count))
        return True

    def _on_trash_files(self, fnames: List[str]):
        if not askUser(tr(StringsGroup.MEDIA_CHECK, "delete-unused-confirm")):
            return

        self.progress_dialog = self.mw.progress.start()

        last_progress = time.time()
        remaining = len(fnames)
        total = len(fnames)
        try:
            for chunk in chunked_list(fnames, 25):
                self.mw.col.media.trash_files(chunk)
                remaining -= len(chunk)
                if time.time() - last_progress >= 0.3:
                    self.mw.progress.update(
                        tr(StringsGroup.MEDIA_CHECK, "files-remaining", count=remaining)
                    )
        finally:
            self.mw.progress.finish()
            self.progress_dialog = None

        tooltip(tr(StringsGroup.MEDIA_CHECK, "delete-unused-complete", count=total))
