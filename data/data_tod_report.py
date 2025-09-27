from enum import Enum

boss_config = {
    "Queen Ant": {"epic": True,  "drop_ring": True,  "respawn": (24  * 3600), "window": (4 * 3600)},
    "Zaken":     {"epic": True,  "drop_ring": False, "respawn": (45  * 3600), "window": (4 * 3600)},
    "Baium":     {"epic": True,  "drop_ring": False, "respawn": (125 * 3600), "window": (4 * 3600)},
    "Antharas":  {"epic": True,  "drop_ring": False, "respawn": (192 * 3600), "window": (4 * 3600)},
    "Valakas":   {"epic": True,  "drop_ring": False, "respawn": (264 * 3600), "window": (4 * 3600)},
    "Cabrio":    {"epic": False, "drop_ring": False, "respawn": (12  * 3600), "window": (9 * 3600)},
    "Hallate":   {"epic": False, "drop_ring": False, "respawn": (12  * 3600), "window": (9 * 3600)},
    "Kernon":    {"epic": False, "drop_ring": False, "respawn": (12  * 3600), "window": (9 * 3600)},
    "Golkonda":  {"epic": False, "drop_ring": False, "respawn": (12  * 3600), "window": (9 * 3600)},
    "Barakiel":  {"epic": False, "drop_ring": False, "respawn": (12  * 3600), "window": (9 * 3600)},
}

sides = {
    "Zone": "Zone ⚫",
    "0n573pb3f0r3": "0n573pb3f0r3 🦅",
    "China": "China 🇨🇳",
    "Others": "others ❓"
}

class DropRing(Enum):
    YES = "✅"
    NO = "❌"



