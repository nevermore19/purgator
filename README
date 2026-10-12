# Purgator

App for purging stale cache files, temp files and project build artifacts.
Qt (PySide6) GUI with background workers and an in-app cron scheduler.

## Setup

    scripts/setup.sh           # Arch / Debian 13+: distro PySide6, native theme
    scripts/setup.sh --pip-qt  # anywhere else: PySide6 from PyPI (Fusion look)

## Run

    .venv/bin/purgator                  # GUI
    .venv/bin/purgator --run user_cache # headless dry run, prints what would be removed
    .venv/bin/purgator --run project_builds --root ~/Development --delete

Tasks: user_cache, stale_files, project_builds. Everything is a dry run unless
"Dry run" is unchecked in the GUI or --delete is passed.

## Layout

    src/purgator/
      tasks/       purge task definitions (PurgeTask subclasses)
      workers.py   QThreadPool-based runner; GUI updates only via signals
      scheduler.py cron expressions -> TaskRunner, jobs stored in QSettings
      ui/          main window
