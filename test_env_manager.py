import sys
from pathlib import Path
import shutil  # Added import for shutil

import pytest

# Ensure the repository root is in the module search path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import functions and classes from your module.
from env_manager import (
    Environment,
    scan_venv_dirs,
    scan_current_dir_venv,
    scan_conda_envs,
    is_current_env,
    delete_environment,
)

# ----------------------------------------------------------------------
# Test scanning for standard virtual environments (venv/virtualenv)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_venv_dirs(tmp_path, monkeypatch):
    # Create a fake venv directory with a pyvenv.cfg file.
    fake_venv_dir = tmp_path / "venv_test"
    fake_venv_dir.mkdir()
    (fake_venv_dir / "pyvenv.cfg").write_text("home = /usr/bin")

    # Monkey-patch Path.home() to return tmp_path.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    envs = await scan_venv_dirs()

    # Check that our fake environment is found.
    names = [env.name for env in envs]
    assert fake_venv_dir.name in names

# ----------------------------------------------------------------------
# Test scanning for in-project virtual environment (.venv)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_current_dir_venv(tmp_path, monkeypatch):
    # Create a fake project directory.
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    fake_venv = project_dir / ".venv"
    fake_venv.mkdir()
    (fake_venv / "pyvenv.cfg").write_text("home = /usr/bin")

    # Change the current working directory to the fake project.
    monkeypatch.chdir(project_dir)

    envs = await scan_current_dir_venv()
    assert len(envs) == 1
    assert envs[0].env_type == "venv (local)"
    assert project_dir.name == envs[0].name

# ----------------------------------------------------------------------
# Test is_current_env function.
# ----------------------------------------------------------------------
def test_is_current_env(tmp_path):
    # Create a fake environment directory.
    fake_env = tmp_path / "fake_env"
    fake_env.mkdir()

    # Since the current Python executable is not inside fake_env,
    # is_current_env should return False.
    result = is_current_env(str(fake_env))
    assert result is False

# ----------------------------------------------------------------------
# Test deletion of a virtual environment.
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_environment(tmp_path):
    # Create a temporary fake virtual environment.
    fake_env = tmp_path / "env_to_delete"
    fake_env.mkdir()
    (fake_env / "pyvenv.cfg").write_text("home = /usr/bin")
    env = Environment(name="env_to_delete", env_type="venv", path=str(fake_env.resolve()))

    # Ensure the directory exists before deletion.
    assert fake_env.exists()

    success, message = await delete_environment(env)
    assert success, f"Deletion failed: {message}"
    assert not fake_env.exists()

# ----------------------------------------------------------------------
# Test scanning for Conda environments in manual mode.
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_conda_envs_manual(tmp_path, monkeypatch):
    # Simulate that the conda CLI is not found.
    monkeypatch.setattr(shutil, "which", lambda x: None)

    # Create a fake Conda environment directory under a known path.
    fake_conda_env_dir = tmp_path / "miniconda3" / "envs" / "fake_conda_env"
    fake_conda_env_dir.mkdir(parents=True)
    # Create a fake conda-meta directory to indicate a Conda environment.
    (fake_conda_env_dir / "conda-meta").mkdir()

    # Set HOME to tmp_path so that our manual scan finds the fake directory.
    monkeypatch.setenv("HOME", str(tmp_path))

    envs = await scan_conda_envs()

    # Verify that our fake Conda environment is found.
    names = [env.name for env in envs]
    assert "fake_conda_env" in names
