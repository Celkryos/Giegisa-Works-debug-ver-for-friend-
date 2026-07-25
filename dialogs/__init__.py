from .calendar import ScheduleAlertDialog, CheckinAlertDialog, EditScheduleDialog, EditCheckinDialog, ScheduleDialog, DayDetailDialog, MiniCalendarDialog, CheckinDialog, StatsDialog
from .notes import EditNoteDialog, QuickNoteDialog, NotesManagerDialog
from .settings import UserProfileDialog, MoodDialog, DistractionSettingsDialog, AutoEventSettingsDialog, ApiSettingsDialog, AppearanceDialog, FocusDialog, MemorySettingsDialog
from .library import CollectionManagerDialog, StoreDialog, HistoryDialog
from .random_event import RandomEventDialog
from .ebook import EbookShelfDialog, EbookReaderDialog, ImagePreviewDialog

__all__ = [name for name in globals() if name.endswith("Dialog")]
