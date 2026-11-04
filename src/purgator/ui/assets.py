from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QPainter, QPixmap

from purgator.ui import colors

ICONS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "icons"

# The sizes the icon is rasterised at; the widgets pick the closest one.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 256)


def themed_icon(path: Path, color: str | None = None) -> QIcon:
    """Draw an SVG icon in the colour of the active theme."""
    if color is None:
        dark = QColor(colors.BACKGROUND).lightness() < 128
        color = colors.TEXT if dark else colors.ACCENT

    reader = QImageReader(str(path))
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(QSize(size.width() * 4, size.height() * 4))
    image = reader.read()
    if image.isNull():
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return QIcon(str(path))
        image = pixmap.toImage()

    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), QColor(color))
    painter.end()

    icon = QIcon()
    for edge in ICON_SIZES:
        pixmap = QPixmap.fromImage(
            image.scaled(
                edge,
                edge,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        icon.addPixmap(pixmap)
    return icon
