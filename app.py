import os
import re
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF, QStringListModel
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontDatabase, QKeySequence, QPainter, QTextCharFormat,
    QSyntaxHighlighter, QTextCursor, QShortcut, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QMainWindow, QMessageBox, QPlainTextEdit, QSplitter,
    QStatusBar, QWidget, QCompleter
)


PLANTUML_KEYWORDS = [
    '@startuml', '@enduml', 'actor', 'participant', 'boundary', 'control',
    'entity', 'database', 'collections', 'queue', 'autonumber', 'activate',
    'deactivate', 'destroy', 'group', 'alt', 'else', 'opt', 'loop', 'par',
    'break', 'critical', 'note', 'left', 'right', 'of', 'over', 'title',
    'header', 'footer', 'legend', 'endlegend', 'skinparam', 'hide', 'show',
    'package', 'rectangle', 'component', 'interface', 'enum', 'class',
    'abstract', 'annotation', 'protocol', 'struct', 'object', 'map',
    'json', 'state', 'usecase', 'folder', 'frame', 'cloud', 'node',
    'artifact', 'card', 'file', 'person', 'start', 'stop', 'endif', 'if',
    'then', 'repeat', 'while', 'fork', 'end fork', 'partition', 'as',
    'return', '->', '-->', '<--', '<->', ':', 'end', 'newpage', 'caption'
]


class PlantUMLHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor('#569CD6'))
        keyword_format.setFontWeight(QFont.Bold)

        preprocessor_format = QTextCharFormat()
        preprocessor_format.setForeground(QColor('#C586C0'))
        preprocessor_format.setFontWeight(QFont.Bold)

        string_format = QTextCharFormat()
        string_format.setForeground(QColor('#CE9178'))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor('#6A9955'))
        comment_format.setFontItalic(True)

        arrow_format = QTextCharFormat()
        arrow_format.setForeground(QColor('#DCDCAA'))
        arrow_format.setFontWeight(QFont.Bold)

        stereotype_format = QTextCharFormat()
        stereotype_format.setForeground(QColor('#4EC9B0'))

        for kw in sorted(PLANTUML_KEYWORDS, key=len, reverse=True):
            pattern = r'(?<!\w)' + re.escape(kw) + r'(?!\w)'
            fmt = preprocessor_format if kw.startswith('@') else keyword_format
            self.rules.append((re.compile(pattern), fmt))

        self.rules.extend([
            (re.compile(r'".*?"'), string_format),
            (re.compile(r"'.*$"), comment_format),
            (re.compile(r'/\'.*?\'/', re.DOTALL), comment_format),
            (re.compile(r'<<?.*?>>'), stereotype_format),
            (re.compile(r'<?-+>?|<<?[-.]*>?>?|<\|--|\*--|o--|--o|--\*'), arrow_format),
        ])

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)


class PlantUMLEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(' '))
        font = QFont('DejaVu Sans Mono')
        if not font.exactMatch():
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self.completer = QCompleter(sorted(PLANTUML_KEYWORDS), self)
        self.completer.setWidget(self)
        self.completer.setModel(QStringListModel(sorted(PLANTUML_KEYWORDS), self.completer))
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)

        self.shortcut = QShortcut(QKeySequence('Ctrl+Space'), self)
        self.shortcut.activated.connect(self.show_completions)

    def insert_completion(self, completion: str):
        tc = self.textCursor()
        extra = len(self.completion_prefix())
        if extra > 0:
            for _ in range(extra):
                tc.deletePreviousChar()
        tc.insertText(completion)
        self.setTextCursor(tc)

    def completion_prefix(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.WordUnderCursor)
        word = tc.selectedText()
        if word:
            return word

        pos = self.textCursor().positionInBlock()
        line = self.textCursor().block().text()[:pos]
        m = re.search(r'([@A-Za-z_][A-Za-z0-9_<>-]*)$', line)
        return m.group(1) if m else ''

    def show_completions(self):
        prefix = self.completion_prefix()
        self.completer.setCompletionPrefix(prefix)
        popup = self.completer.popup()
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        cr = self.cursorRect()
        cr.setWidth(max(280, popup.sizeHintForColumn(0) + 24))
        self.completer.complete(cr)

    def keyPressEvent(self, event):
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            current = popup.currentIndex()
            if current.isValid():
                self.insert_completion(current.data())
                popup.hide()
                event.accept()
                return
        super().keyPressEvent(event)


class ImagePreview(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setBackgroundBrush(Qt.white)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self._pixmap_item)
        self._current_pixmap = QPixmap()
        self._zoom_factor = 1.0

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale_image(factor)

    def scale_image(self, factor: float):
        self._zoom_factor *= factor
        self.scale(factor, factor)

    def load_image(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        self._current_pixmap = pixmap
        self._pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.viewport().update()
        return True

    def fit_image(self):
        if not self._current_pixmap.isNull():
            self.resetTransform()
            self._zoom_factor = 1.0
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def actual_size(self):
        if not self._current_pixmap.isNull():
            self.resetTransform()
            self._zoom_factor = 1.0
            self.centerOn(self._pixmap_item)
            self.viewport().update()

    def has_image(self):
        return not self._current_pixmap.isNull()

    def copy_to_clipboard(self):
        if self._current_pixmap.isNull():
            return False
        QApplication.clipboard().setPixmap(self._current_pixmap)
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PlantUML Previewer')
        self.resize(1400, 850)

        self.current_file = None
        self.temp_dir = tempfile.TemporaryDirectory(prefix='plantuml_previewer_')
        self.image_path = os.path.join(self.temp_dir.name, 'preview.png')
        self._first_render = True

        self.editor = PlantUMLEditor()
        self.highlighter = PlantUMLHighlighter(self.editor.document())

        self.preview = ImagePreview()

        splitter = QSplitter()
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(350)
        self.render_timer.timeout.connect(self.render_uml)

        self.editor.textChanged.connect(self.schedule_render)

        self.build_actions()
        self.load_default_text()
        self.schedule_render()

    def build_actions(self):
        open_action = QAction('Open', self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file)

        save_action = QAction('Save', self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_file)

        save_as_action = QAction('Save As', self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_file_as)

        copy_image_action = QAction('Copy Image', self)
        copy_image_action.setShortcut('Ctrl+Shift+C')
        copy_image_action.triggered.connect(self.copy_image)

        fit_action = QAction('Fit Image', self)
        fit_action.setShortcut('Ctrl+0')
        fit_action.triggered.connect(self.preview.fit_image)

        actual_size_action = QAction('100%', self)
        actual_size_action.setShortcut('Ctrl+1')
        actual_size_action.triggered.connect(self.preview.actual_size)

        render_action = QAction('Render Now', self)
        render_action.setShortcut('F5')
        render_action.triggered.connect(self.render_uml)

        file_menu = self.menuBar().addMenu('File')
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)

        edit_menu = self.menuBar().addMenu('Edit')
        edit_menu.addAction(copy_image_action)

        view_menu = self.menuBar().addMenu('View')
        view_menu.addAction(fit_action)
        view_menu.addAction(actual_size_action)

        build_menu = self.menuBar().addMenu('Build')
        build_menu.addAction(render_action)

    def load_default_text(self):
        self.editor.setPlainText(
            "@startuml\n"
            "title Simple demo\n"
            "actor User\n"
            "participant App\n"
            "database Cache\n"
            "User -> App : Open previewer\n"
            "activate App\n"
            "App -> Cache : Read recent file\n"
            "Cache --> App : Result\n"
            "App --> User : Show PNG preview\n"
            "deactivate App\n"
            "@enduml\n"
        )

    def plantuml_command(self):
        env_cmd = os.environ.get('PLANTUML_CMD')
        if env_cmd:
            return env_cmd
        return shutil.which('plantuml') or 'plantuml'

    def plantuml_dpi(self):
        return os.environ.get('PLANTUML_DPI', '192')

    def schedule_render(self):
        self.render_timer.start()

    def render_uml(self):
        source_path = os.path.join(self.temp_dir.name, 'preview.puml')
        Path(source_path).write_text(self.editor.toPlainText(), encoding='utf-8')

        cmd = [self.plantuml_command(), '-tpng', '-DPLANTUML_LIMIT_SIZE=16384', f'-dpi{self.plantuml_dpi()}', source_path]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            self.status.showMessage('plantuml command not found. Set PLANTUML_CMD or install plantuml.', 8000)
            return
        except Exception as exc:
            self.status.showMessage(f'Failed to start PlantUML: {exc}', 8000)
            return

        rendered_image = os.path.splitext(source_path)[0] + '.png'
        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip() or 'PlantUML rendering failed.'
            self.status.showMessage(msg, 8000)
            return

        if not os.path.exists(rendered_image):
            self.status.showMessage('PlantUML finished but no PNG was produced.', 8000)
            return

        if not self.preview.load_image(rendered_image):
            self.status.showMessage('PNG was produced but could not be loaded.', 8000)
            return

        if self._first_render:
            self.preview.fit_image()
            self._first_render = False

        self.status.showMessage(f'Rendered successfully ({self.plantuml_dpi()} dpi).', 1500)

    def copy_image(self):
        if self.preview.copy_to_clipboard():
            self.status.showMessage('Image copied to clipboard.', 2000)
        else:
            self.status.showMessage('No image to copy.', 2000)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open PlantUML file', '', 'PlantUML Files (*.puml *.plantuml *.uml *.txt);;All Files (*)'
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding='utf-8')
        except Exception as exc:
            QMessageBox.critical(self, 'Open failed', str(exc))
            return
        self.editor.setPlainText(text)
        self.current_file = path
        self.status.showMessage(f'Opened {path}', 3000)

    def save_file(self):
        if not self.current_file:
            return self.save_file_as()
        try:
            Path(self.current_file).write_text(self.editor.toPlainText(), encoding='utf-8')
        except Exception as exc:
            QMessageBox.critical(self, 'Save failed', str(exc))
            return
        self.status.showMessage(f'Saved {self.current_file}', 3000)

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save PlantUML file', '', 'PlantUML Files (*.puml *.plantuml *.uml);;Text Files (*.txt);;All Files (*)'
        )
        if not path:
            return
        self.current_file = path
        self.save_file()

    def closeEvent(self, event):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
