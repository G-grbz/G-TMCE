# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .core import bundled_resource_path


@dataclass(frozen=True)
class ThemePalette:
    window: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    disabled: str
    danger: str
    success: str
    selection: str


DARK = ThemePalette(
    window="#0b1424",
    surface="#101c2e",
    surface_alt="#142238",
    surface_hover="#1a2b46",
    border="#2a3d5c",
    border_strong="#3b5278",
    text="#f4f7ff",
    muted="#9aa9c8",
    accent="#6256ff",
    accent_hover="#756cff",
    accent_pressed="#5045e8",
    accent_soft="#26265a",
    disabled="#62708b",
    danger="#ff5f6d",
    success="#29c983",
    selection="#2b3d66",
)

LIGHT = ThemePalette(
    window="#eef2f8",
    surface="#ffffff",
    surface_alt="#f6f8fc",
    surface_hover="#edf1f8",
    border="#d8dfeb",
    border_strong="#bec9da",
    text="#172033",
    muted="#68758f",
    accent="#5548ee",
    accent_hover="#665af5",
    accent_pressed="#463bd0",
    accent_soft="#efedff",
    disabled="#a7afbf",
    danger="#d92d42",
    success="#188a52",
    selection="#e7e9ff",
)


def palette_for(mode: str) -> ThemePalette:
    return LIGHT if str(mode).lower() == "light" else DARK


def theme_toggle_icon(mode: str) -> QIcon:
    """Return a crisp, font-independent icon for the next theme action."""
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    is_dark = str(mode).lower() == "dark"

    if is_dark:
        # A warm sun communicates that activating this control switches to the
        # light theme without relying on whichever symbol font is installed.
        color = QColor("#ffd166")
        pen = QPen(color, 3.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(17, 17, 14, 14)
        for start_x, start_y, end_x, end_y in (
            (24, 6, 24, 11),
            (24, 37, 24, 42),
            (6, 24, 11, 24),
            (37, 24, 42, 24),
            (11, 11, 15, 15),
            (33, 33, 37, 37),
            (11, 37, 15, 33),
            (33, 15, 37, 11),
        ):
            painter.drawLine(start_x, start_y, end_x, end_y)
    else:
        # Draw a true crescent rather than a Unicode glyph so it retains the
        # same refined shape on every supported desktop platform.
        outer = QPainterPath()
        outer.addEllipse(11, 9, 25, 25)
        inner = QPainterPath()
        inner.addEllipse(19, 6, 25, 25)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#536785"))
        painter.drawPath(outer.subtracted(inner))

    painter.end()
    return QIcon(pixmap)


def build_stylesheet(mode: str) -> str:
    p = palette_for(mode)
    arrow_name = "combo-arrow-light.png" if str(mode).lower() == "light" else "combo-arrow-dark.png"
    arrow_url = bundled_resource_path(arrow_name).as_posix()
    tab_arrow_variant = "light" if str(mode).lower() == "light" else "dark"
    tab_left_arrow = bundled_resource_path(f"tab-arrow-left-{tab_arrow_variant}.png").as_posix()
    tab_right_arrow = bundled_resource_path(f"tab-arrow-right-{tab_arrow_variant}.png").as_posix()
    return f"""
    * {{
        font-family: 'Inter', 'Noto Sans', 'Segoe UI', sans-serif;
        font-size: 12px;
        color: {p.text};
    }}
    QMainWindow, QDialog, QWidget#AppRoot, QWidget#DialogRoot, QScrollArea#MainScroll,
    QScrollArea#DialogScroll, QScrollArea#MainScroll > QWidget > QWidget,
    QScrollArea#DialogScroll > QWidget > QWidget {{
        background: {p.window};
    }}
    QWidget#Header {{ background: transparent; }}
    QLabel#AppName {{ font-size: 20px; font-weight: 800; color: {p.text}; }}
    QLabel#Version {{ font-size: 12px; color: #aab5ff; font-weight: 600; }}
    QLabel#Tagline, QLabel#Muted, QLabel#StatusText {{ color: {p.muted}; }}
    QLabel#SectionTitle {{ font-size: 15px; font-weight: 800; color: {p.text}; }}
    QLabel#SectionMarker {{ background: {p.accent}; border-radius: 2px; min-width: 4px; max-width: 4px; }}
    QLabel#FieldLabel {{ font-weight: 650; color: {p.text}; background: transparent; }}
    QLabel#TableHeading {{ font-weight: 750; color: {p.text}; background: transparent; }}

    QFrame#Card, QFrame#DialogCard {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QFrame#InnerCard {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 9px;
    }}
    QFrame#Separator {{ background: {p.border}; min-height: 1px; max-height: 1px; border: none; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {p.surface_alt};
        border: 1px solid {p.border_strong};
        border-radius: 7px;
        min-height: 30px;
        padding: 0 9px;
        selection-background-color: {p.accent};
        selection-color: white;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {p.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {p.disabled}; background: {p.surface}; }}
    QComboBox {{ padding-right: 24px; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border: none;
        background: transparent;
    }}
    QComboBox::drop-down:hover, QComboBox::drop-down:pressed {{
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url("{arrow_url}");
        width: 9px;
        height: 5px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface}; border: 1px solid {p.border_strong};
        selection-background-color: {p.selection}; selection-color: {p.text};
        outline: 0;
    }}

    QPushButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border_strong};
        border-radius: 7px;
        min-height: 32px;
        padding: 0 13px;
        font-weight: 650;
    }}
    QPushButton:hover {{ background: {p.surface_hover}; border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.selection}; }}
    QPushButton:disabled {{ color: {p.disabled}; border-color: {p.border}; background: {p.surface}; }}
    QPushButton#PrimaryButton {{
        color: white; background: {p.accent}; border-color: {p.accent}; font-weight: 800;
    }}
    QPushButton#PrimaryButton:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
    QPushButton#PrimaryButton:pressed {{ background: {p.accent_pressed}; }}
    QPushButton#GhostButton {{ background: transparent; border-color: transparent; color: #aab5ff; }}
    QPushButton#GhostButton:hover {{ background: {p.accent_soft}; border-color: {p.border}; }}
    QPushButton#CompactButton {{
        min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
        padding: 0; border-radius: 6px; font-size: 15px; font-weight: 900;
    }}
    QPushButton#CompactButton:disabled {{
        color: {p.disabled}; background: {p.surface}; border-color: {p.border};
    }}
    QPushButton#ThemeButton {{
        min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
        padding: 0; border-radius: 17px;
        background: {p.surface_alt}; border-color: {p.border_strong};
    }}
    QPushButton#ThemeButton:hover {{ background: {p.accent_soft}; border-color: {p.accent}; }}
    QPushButton#ThemeButton:pressed {{ background: {p.selection}; }}
    QPushButton#ThemeButton:focus {{ border: 2px solid {p.accent}; }}

    QCheckBox {{ spacing: 7px; background: transparent; color: {p.text}; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {p.border_strong}; border-radius: 3px;
        background: {p.surface_alt};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    QCheckBox::indicator:checked:disabled {{ background: {p.disabled}; border-color: {p.disabled}; }}

    QProgressBar {{
        background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: 5px;
        min-height: 8px; max-height: 8px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}

    QTableWidget, QTreeWidget, QTreeView {{
        background: {p.surface}; alternate-background-color: {p.surface_alt};
        border: 1px solid {p.border}; border-radius: 8px; gridline-color: {p.border};
        selection-background-color: {p.selection}; selection-color: {p.text};
    }}
    QHeaderView {{ background: {p.surface}; }}
    QHeaderView::section {{
        background: {p.surface}; color: {p.muted}; border: none;
        border-bottom: 1px solid {p.border}; padding: 6px 6px; font-weight: 750;
    }}
    QHeaderView::section:hover {{ background: {p.surface}; color: {p.text}; }}
    QTableCornerButton::section {{ background: {p.surface}; border: none; border-bottom: 1px solid {p.border}; }}

    QPlainTextEdit, QTextEdit {{
        background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: 8px;
        padding: 6px; selection-background-color: {p.accent};
    }}
    QMenu {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
        border-radius: 7px; padding: 5px;
    }}
    QMenu::item {{
        background: transparent; color: {p.text}; border-radius: 5px;
        padding: 7px 26px 7px 10px;
    }}
    QMenu::item:selected {{ background: {p.selection}; color: {p.text}; }}
    QMenu::item:disabled {{ color: {p.disabled}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 7px; }}

    QTabWidget::pane {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {p.surface_alt}; color: {p.muted}; border: 1px solid {p.border};
        border-bottom: none; border-top-left-radius: 7px; border-top-right-radius: 7px;
        padding: 7px 12px; margin-right: 3px; font-weight: 650;
    }}
    QTabBar::tab:hover {{ background: {p.surface_hover}; color: {p.text}; }}
    QTabBar::tab:selected {{
        background: {p.surface}; color: {p.text}; border-color: {p.border_strong};
        border-bottom: 1px solid {p.surface};
    }}
    QTabBar QToolButton {{
        background: {p.surface_alt}; border: 1px solid {p.border_strong}; border-radius: 6px;
        min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0;
    }}
    QTabBar QToolButton:hover {{ background: {p.surface_hover}; border-color: {p.accent}; }}
    QTabBar QToolButton:disabled {{ background: {p.surface}; border-color: {p.border}; }}
    QTabBar::scroller {{ width: 62px; }}
    QTabBar QToolButton::left-arrow {{ image: url("{tab_left_arrow}"); width: 6px; height: 10px; }}
    QTabBar QToolButton::right-arrow {{ image: url("{tab_right_arrow}"); width: 6px; height: 10px; }}
    QScrollArea {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; }}
    QScrollArea > QWidget > QWidget {{ background: {p.surface}; }}

    QFrame#ToastSuccess, QFrame#ToastError {{
        border-radius: 9px; padding: 3px;
    }}
    QFrame#ToastSuccess {{ background: {p.success}; border: 1px solid {p.success}; }}
    QFrame#ToastError {{ background: {p.danger}; border: 1px solid {p.danger}; }}
    QFrame#ToastSuccess QLabel, QFrame#ToastError QLabel {{ color: white; background: transparent; font-weight: 700; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QSlider::groove:horizontal {{ height: 6px; background: {p.border}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 16px; margin: -5px 0; background: {p.text}; border: 2px solid {p.accent}; border-radius: 8px; }}

    QToolTip {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.border_strong}; padding: 5px; }}
    """
