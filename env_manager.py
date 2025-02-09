#!/usr/bin/env python3
"""
A modern Qt6-based GUI for managing Python virtual environments asynchronously.
It scans for venv/virtualenv (including uv/.venv), Pipenv, Poetry, and Conda environments,
and lets you view details and delete them safely.
"""

import os
import sys
import json
import subprocess
import asyncio
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QFormLayout, QTableView, QMessageBox, QLineEdit, QLabel,
    QToolBar, QStatusBar, QAbstractItemView
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer, QSortFilterProxyModel
from PySide6.QtGui import QIcon, QAction

import qasync

# -----------------------------------------------------------------------------
# Data structure representing a Python virtual environment.
# -----------------------------------------------------------------------------
@dataclass
class Environment:
    name: str
    env_type: str
    path: str

# -----------------------------------------------------------------------------
# Table model for displaying environments.
# -----------------------------------------------------------------------------
class EnvTableModel(QAbstractTableModel):
    def __init__(self, environments: List[Environment] = None):
        super().__init__()
        self.environments = environments or []
        self.headers = ["Name", "Type", "Path"]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.environments)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        env = self.environments[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return env.name
            elif index.column() == 1:
                return env.env_type
            elif index.column() == 2:
                return env.path
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return super().headerData(section, orientation, role)

    def update_data(self, environments: List[Environment]):
        self.beginResetModel()
        self.environments = environments
        self.endResetModel()

# -----------------------------------------------------------------------------
# Details panel for a selected environment.
# -----------------------------------------------------------------------------
class DetailsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(300)
        layout = QFormLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.name_label = QLabel("-")
        self.type_label = QLabel("-")
        self.path_label = QLabel("-")
        layout.addRow("Name:", self.name_label)
        layout.addRow("Type:", self.type_label)
        layout.addRow("Path:", self.path_label)

    def update_details(self, env: Environment):
        self.name_label.setText(env.name)
        self.type_label.setText(env.env_type)
        self.path_label.setText(env.path)

    def clear_details(self):
        self.name_label.setText("-")
        self.type_label.setText("-")
        self.path_label.setText("-")

# -----------------------------------------------------------------------------
# Main application window.
# -----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Environment Manager")
        self.resize(1000, 600)

        # Setup toolbar.
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        # Refresh action.
        refresh_action = QAction(QIcon.fromTheme("view-refresh"), "Refresh", self)
        refresh_action.triggered.connect(self.on_refresh_clicked)
        self.toolbar.addAction(refresh_action)
        # Delete action.
        delete_action = QAction(QIcon.fromTheme("edit-delete"), "Delete", self)
        delete_action.triggered.connect(self.on_delete_clicked)
        self.toolbar.addAction(delete_action)
        # Spacer and search.
        self.toolbar.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search environments...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        self.toolbar.addWidget(self.search_edit)

        # Setup status bar.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create central widget with a splitter.
        central_widget = QSplitter(Qt.Horizontal)
        self.setCentralWidget(central_widget)

        # Left side: table view.
        self.env_table_model = EnvTableModel()
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.env_table_model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        central_widget.addWidget(self.table_view)

        # Right side: details panel.
        self.details_panel = DetailsPanel()
        central_widget.addWidget(self.details_panel)

        # Keep a full list of environments.
        self.all_envs: List[Environment] = []

        # Schedule initial refresh after event loop starts.
        QTimer.singleShot(0, lambda: asyncio.create_task(self.refresh_environments()))

    def on_search_changed(self, text: str):
        self.proxy_model.setFilterWildcard(text)

    def on_selection_changed(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes:
            # Get the source model index.
            source_index = self.proxy_model.mapToSource(indexes[0])
            env = self.env_table_model.environments[source_index.row()]
            self.details_panel.update_details(env)
        else:
            self.details_panel.clear_details()

    # Updated slot to accept optional parameter (to handle signal extra parameter)
    def on_refresh_clicked(self, checked: bool = False):
        asyncio.create_task(self.refresh_environments())

    def on_delete_clicked(self, checked: bool = False):
        asyncio.create_task(self.delete_selected())

    async def refresh_environments(self):
        self.status_bar.showMessage("Scanning for environments...")
        try:
            envs = await scan_all_environments()
            # Remove duplicates by path.
            unique = {env.path: env for env in envs}.values()
            self.all_envs = list(unique)
            self.env_table_model.update_data(self.all_envs)
            self.status_bar.showMessage(f"Found {len(self.all_envs)} environments.", 5000)
        except Exception as exc:
            self.status_bar.showMessage(f"Error scanning: {exc}", 5000)

    async def delete_selected(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select an environment to delete.")
            return
        # Map proxy index to source index.
        source_index = self.proxy_model.mapToSource(indexes[0])
        env = self.env_table_model.environments[source_index.row()]
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete the {env.env_type} environment '{env.name}'?\nPath: {env.path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.status_bar.showMessage("Deleting environment...")
        try:
            success, message = await delete_environment(env)
            if success:
                QMessageBox.information(self, "Deleted", message)
            else:
                QMessageBox.critical(self, "Deletion Failed", message)
        except Exception as exc:
            QMessageBox.critical(self, "Deletion Error", str(exc))
        await self.refresh_environments()

# -----------------------------------------------------------------------------
# Asynchronous scanning functions.
# -----------------------------------------------------------------------------
async def scan_all_environments() -> List[Environment]:
    results = await asyncio.gather(
        scan_venv_dirs(),
        scan_conda_envs(),
        scan_current_dir_venv(),
        return_exceptions=True
    )
    envs: List[Environment] = []
    for result in results:
        if isinstance(result, Exception):
            print("Error in scanning:", result)
        else:
            envs.extend(result)
    return envs

async def scan_venv_dirs() -> List[Environment]:
    """Scan common directories for venv/virtualenv (and uv) environments."""
    def blocking_scan() -> List[Environment]:
        envs: List[Environment] = []
        home = Path.home()
        paths = [
            home / ".virtualenvs",
            home / ".cache" / "pypoetry" / "virtualenvs",
            home / ".local" / "share" / "virtualenvs",
            ]
        for base in paths:
            if base.is_dir():
                try:
                    for entry in base.iterdir():
                        if entry.is_dir() and (entry / "pyvenv.cfg").exists():
                            etype = "Poetry" if "pypoetry" in str(base) else "Pipenv" if "local" in str(base) else "venv"
                            envs.append(Environment(name=entry.name, env_type=etype, path=str(entry.resolve())))
                except Exception as exc:
                    print(f"Error scanning {base}: {exc}")
        return envs
    return await asyncio.to_thread(blocking_scan)

async def scan_conda_envs() -> List[Environment]:
    """Scan for Conda environments via CLI; if missing, scan known directories."""
    def blocking_conda_scan() -> List[Environment]:
        envs: List[Environment] = []
        conda_path = shutil.which("conda")
        if conda_path:
            try:
                result = subprocess.run(
                    [conda_path, "env", "list", "--json"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                data = json.loads(result.stdout)
                for path in data.get("envs", []):
                    envs.append(Environment(name=Path(path).name, env_type="Conda", path=path))
            except Exception as exc:
                print("Error scanning Conda via CLI:", exc)
        else:
            print("Conda CLI not found; performing manual scan.")
            known_dirs = [
                Path.home() / "miniconda3" / "envs",
                Path.home() / "anaconda3" / "envs",
                Path.home() / ".conda" / "envs"
            ]
            for base in known_dirs:
                if base.is_dir():
                    try:
                        for env_dir in base.iterdir():
                            if env_dir.is_dir():
                                if (env_dir / "conda-meta").is_dir() or (env_dir / "bin" / "python").exists():
                                    envs.append(Environment(name=env_dir.name, env_type="Conda", path=str(env_dir.resolve())))
                    except Exception as exc:
                        print(f"Error scanning {base}: {exc}")
        return envs
    return await asyncio.to_thread(blocking_conda_scan)

async def scan_current_dir_venv() -> List[Environment]:
    """Check the current directory for an in-project '.venv' environment."""
    def blocking_scan() -> List[Environment]:
        envs: List[Environment] = []
        cwd = Path.cwd()
        potential = cwd / ".venv"
        if potential.is_dir() and (potential / "pyvenv.cfg").exists():
            envs.append(Environment(name=cwd.name, env_type="venv (local)", path=str(potential.resolve())))
        return envs
    return await asyncio.to_thread(blocking_scan)

# -----------------------------------------------------------------------------
# Environment deletion (with safety checks).
# -----------------------------------------------------------------------------
def is_current_env(env_path: str) -> bool:
    """Return True if env_path is the one running this application."""
    try:
        return Path(sys.executable).resolve().as_posix().startswith(Path(env_path).resolve().as_posix())
    except (OSError, RuntimeError):
        return False

async def delete_environment(env: Environment) -> Tuple[bool, str]:
    if is_current_env(env.path):
        return False, "Cannot delete the environment currently in use."
    if env.env_type == "Conda":
        if env.name.lower() == "base":
            return False, "Cannot delete the Conda base environment."
        def blocking_delete() -> Tuple[bool, str]:
            try:
                subprocess.run(
                    ["conda", "env", "remove", "--prefix", env.path, "-y"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                return True, "Conda environment removed successfully."
            except Exception as exc:
                return False, f"Error deleting Conda environment: {exc}"
        return await asyncio.to_thread(blocking_delete)
    else:
        def blocking_delete() -> Tuple[bool, str]:
            try:
                shutil.rmtree(env.path)
                return True, "Environment removed successfully."
            except Exception as exc:
                return False, f"Error deleting environment: {exc}"
        return await asyncio.to_thread(blocking_delete)

# -----------------------------------------------------------------------------
# Main entry point.
# -----------------------------------------------------------------------------
def main():
    # Enable high-DPI scaling.
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    main_win = MainWindow()
    main_win.show()
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
