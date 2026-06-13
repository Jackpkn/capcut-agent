import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from capcut.reader import PROJECTS_PATH

logger = logging.getLogger(__name__)


class ProjectChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith("draft_info.json"):
            logger.info("Project file changed: %s", event.src_path)


_observer: Observer | None = None


def start_watcher() -> bool:
    global _observer
    if _observer is not None:
        return True

    if not PROJECTS_PATH.exists():
        logger.warning("CapCut projects path not found: %s", PROJECTS_PATH)
        return False

    _observer = Observer()
    _observer.schedule(ProjectChangeHandler(), str(PROJECTS_PATH), recursive=True)
    _observer.start()
    logger.info("Watching CapCut projects at %s", PROJECTS_PATH)
    return True


def stop_watcher():
    global _observer
    if _observer is not None:
        _observer.stop()
        _observer.join()
        _observer = None
