import os
import json
from datetime import datetime

DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "ott_notifier_db").strip()
DATA_FILE = os.getenv("DATA_FILE", "shows_data.json").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

mongo_client = None
shows_col = None
users_col = None

if DATABASE_URI:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(DATABASE_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db_instance = mongo_client[DATABASE_NAME]
        shows_col = db_instance["shows"]
        users_col = db_instance["authorized_users"]
        print(f"[✓] Connected to MongoDB Atlas! Database: '{DATABASE_NAME}'")
    except Exception as e:
        print(f"[!] MongoDB Atlas connection failed ({e}). Falling back to local '{DATA_FILE}'.")
        mongo_client = None
        shows_col = None
        users_col = None
else:
    print(f"[*] No DATABASE_URI provided. Using local file storage ('{DATA_FILE}').")


def load_local_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"shows": {}, "authorized_users": []}
    return {"shows": {}, "authorized_users": []}


def save_local_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_storage_name() -> str:
    return f"MongoDB Atlas ({DATABASE_NAME})" if shows_col is not None else f"Local JSON ({DATA_FILE})"


# --- Shows DB Functions ---
def db_get_all_shows() -> dict:
    if shows_col is not None:
        try:
            docs = list(shows_col.find({}))
            return {doc["show_id"]: doc for doc in docs}
        except Exception as e:
            print(f"[!] MongoDB read error: {e}")
    return load_local_db().get("shows", {})


def db_get_show(show_id: str) -> dict | None:
    if shows_col is not None:
        try:
            return shows_col.find_one({"show_id": show_id})
        except Exception as e:
            print(f"[!] MongoDB find error: {e}")
    return load_local_db().get("shows", {}).get(show_id)


def db_save_new_show(show_data: dict):
    show_id = show_data["show_id"]
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$set": show_data}, upsert=True)
            return
        except Exception as e:
            print(f"[!] MongoDB save error: {e}")

    data = load_local_db()
    data.setdefault("shows", {})[show_id] = show_data
    save_local_db(data)


def db_update_cached_episodes(show_id: str, episodes: list[dict]):
    """Stores latest episode details for instant /getepisode lookups."""
    recent_eps = episodes[:30]
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$set": {"cached_episodes": recent_eps}})
            return
        except Exception as e:
            print(f"[!] MongoDB cache update error: {e}")

    data = load_local_db()
    shows = data.setdefault("shows", {})
    if show_id in shows:
        shows[show_id]["cached_episodes"] = recent_eps
        save_local_db(data)


def db_add_subscriber(show_id: str, chat_id: int):
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$addToSet": {"subscribers": chat_id}})
            return
        except Exception as e:
            print(f"[!] MongoDB subscriber add error: {e}")

    data = load_local_db()
    shows = data.setdefault("shows", {})
    if show_id in shows:
        subs = shows[show_id].setdefault("subscribers", [])
        if chat_id not in subs:
            subs.append(chat_id)
            save_local_db(data)


def db_remove_subscriber(show_id: str, chat_id: int) -> str | None:
    if shows_col is not None:
        try:
            doc = shows_col.find_one({"show_id": show_id})
            if not doc:
                return None
            serial_name = doc.get("serial_name", "Show")
            shows_col.update_one({"show_id": show_id}, {"$pull": {"subscribers": chat_id}})
            updated = shows_col.find_one({"show_id": show_id})
            if updated and not updated.get("subscribers"):
                shows_col.delete_one({"show_id": show_id})
            return serial_name
        except Exception as e:
            print(f"[!] MongoDB remove subscriber error: {e}")

    data = load_local_db()
    shows = data.get("shows", {})
    if show_id in shows and chat_id in shows[show_id].get("subscribers", []):
        serial_name = shows[show_id].get("serial_name", "Show")
        shows[show_id]["subscribers"].remove(chat_id)
        if not shows[show_id]["subscribers"]:
            del shows[show_id]
        save_local_db(data)
        return serial_name
    return None


def db_add_seen_episode(show_id: str, ep_id: str):
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$addToSet": {"seen_episode_ids": ep_id}})
            return
        except Exception as e:
            print(f"[!] MongoDB add seen error: {e}")

    data = load_local_db()
    shows = data.get("shows", {})
    if show_id in shows:
        seen = set(shows[show_id].get("seen_episode_ids", []))
        seen.add(ep_id)
        shows[show_id]["seen_episode_ids"] = list(seen)
        save_local_db(data)


def db_get_user_shows(chat_id: int) -> list[dict]:
    if shows_col is not None:
        try:
            return list(shows_col.find({"subscribers": chat_id}))
        except Exception as e:
            print(f"[!] MongoDB user shows error: {e}")
    shows = load_local_db().get("shows", {})
    return [s for s in shows.values() if chat_id in s.get("subscribers", [])]


def db_get_all_target_chats() -> set:
    """Collect all unique user/channel chat IDs for broadcast announcements."""
    chats = set()
    all_shows = db_get_all_shows()
    for s in all_shows.values():
        for sub in s.get("subscribers", []):
            chats.add(sub)
    for u in db_get_authorized_users():
        chats.add(u)
    return chats


# --- User Authorization DB Functions ---
def db_get_authorized_users() -> set:
    users = set()
    if ADMIN_ID:
        try:
            users.add(int(ADMIN_ID))
        except ValueError:
            pass

    if users_col is not None:
        try:
            docs = list(users_col.find({}))
            for d in docs:
                users.add(d["user_id"])
            return users
        except Exception as e:
            print(f"[!] MongoDB get users error: {e}")

    local_users = load_local_db().get("authorized_users", [])
    users.update(local_users)
    return users


def db_add_user(user_id: int):
    if users_col is not None:
        try:
            users_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id, "added_at": datetime.utcnow()}}, upsert=True)
            return
        except Exception as e:
            print(f"[!] MongoDB add user error: {e}")

    data = load_local_db()
    users = set(data.setdefault("authorized_users", []))
    users.add(user_id)
    data["authorized_users"] = list(users)
    save_local_db(data)


def db_remove_user(user_id: int):
    if users_col is not None:
        try:
            users_col.delete_one({"user_id": user_id})
            return
        except Exception as e:
            print(f"[!] MongoDB remove user error: {e}")

    data = load_local_db()
    users = set(data.get("authorized_users", []))
    users.discard(user_id)
    data["authorized_users"] = list(users)
    save_local_db(data)


# ------------------ PERMISSIONS & ROLES ------------------
def is_admin(user_id: int) -> bool:
    if not ADMIN_ID:
        return True
    return str(user_id) == str(ADMIN_ID)


def is_authorized(user_id: int) -> bool:
    if not ADMIN_ID:
        return True
    if is_admin(user_id):
        return True
    return user_id in db_get_authorized_users()
