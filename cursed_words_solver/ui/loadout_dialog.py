"""Manual loadout editor when run_state.json is missing."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from cursed_words_solver.models import Loadout, LoadoutItem


class LoadoutDialog(QDialog):
    def __init__(self, loadout: Loadout | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Loadout (optional)")
        self.setMinimumWidth(400)
        lo = loadout or Loadout()
        self._preserved_boss_effect = lo.boss_effect
        self._preserved_extras = dict(lo.extras)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.money = QSpinBox()
        self.money.setRange(0, 999999)
        self.money.setValue(lo.money)
        form.addRow("Money", self.money)

        self.character = QLineEdit(lo.character)
        form.addRow("Character", self.character)

        self.pin_branch = QLineEdit(lo.pin_branch)
        self.pin_branch.setPlaceholderText("left, right, or empty")
        form.addRow("Pin branch", self.pin_branch)

        self.boss_id = QLineEdit(lo.boss_id)
        form.addRow("Boss ID", self.boss_id)

        self.boss_name = QLineEdit(lo.boss_name)
        form.addRow("Boss name", self.boss_name)

        self.stickers = QTextEdit()
        self.stickers.setPlaceholderText(
            "One per line: id|name|level\n"
            "e.g. sticky_plaster|Sticky Plaster|2"
        )
        if lo.stickers:
            self.stickers.setPlainText(
                "\n".join(f"{s.id}|{s.name}|{s.level}" for s in lo.stickers)
            )
        form.addRow("Stickers", self.stickers)

        self.stamps = QTextEdit()
        self.stamps.setPlaceholderText("One per line: id|name")
        if lo.stamps:
            self.stamps.setPlainText("\n".join(f"{s.id}|{s.name}" for s in lo.stamps))
        form.addRow("Stamps", self.stamps)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_loadout(self) -> Loadout:
        stickers = []
        for line in self.stickers.toPlainText().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                stickers.append(
                    LoadoutItem(
                        id=parts[0],
                        name=parts[1],
                        level=int(parts[2]) if len(parts) > 2 else 1,
                        kind="sticker",
                    )
                )
        stamps = []
        for line in self.stamps.toPlainText().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                stamps.append(
                    LoadoutItem(id=parts[0], name=parts[1], kind="stamp")
                )
        return Loadout(
            character=self.character.text(),
            pin_branch=self.pin_branch.text().strip(),
            stickers=stickers,
            stamps=stamps,
            boss_id=self.boss_id.text(),
            boss_name=self.boss_name.text(),
            boss_effect=self._preserved_boss_effect,
            money=self.money.value(),
            extras=dict(self._preserved_extras),
        )
