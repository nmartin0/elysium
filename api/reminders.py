"""The timer service's handler for a person's reminder (core/reminders.py).

Here rather than in core because it needs the running server's stores:
where notifications are kept, and whether the owner is still an active
account.
"""

from pathlib import Path


def reminder_timer(app, firing) -> None:
    from core.notifications import NotificationStore
    from core.reminders import fire
    from core.user_directory import UserDirectory

    data_dir = Path(app.state.runtime_paths.data_dir)
    directory = UserDirectory(data_dir / "credentials.db", app.state.generation.config.roles)

    def active(user_id: str) -> bool:
        # EXISTS AND IS NOT DISABLED. is_user_disabled() answers False for
        # an account that does not exist, by its own contract; an unknown
        # user comes back from get_user_record() with no role.
        try:
            return (directory.get_user_record(user_id).role_name is not None
                    and not directory.is_user_disabled(user_id))
        except Exception:  # noqa: BLE001 - an account that cannot be read is not reminded
            return False

    fire(NotificationStore(data_dir / "notifications.db"), active, firing)
