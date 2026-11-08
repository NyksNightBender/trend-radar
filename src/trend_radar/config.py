"""Constants and tunable thresholds."""

from __future__ import annotations

from dataclasses import asdict, dataclass

PROJECT = "tr.wikipedia"
WIKI = "https://tr.wikipedia.org"
PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
ACTION_API = f"{WIKI}/w/api.php"
REPO_URL = "https://github.com/NyksNightBender/trend-radar"
SITE_URL = "https://nyksnightbender.github.io/trend-radar/"
# Wikimedia asks every client to identify itself with a way to reach the operator.
USER_AGENT = f"trend-radar/1.0 (+{REPO_URL})"

# Pages that are not articles: local Turkish namespace names, canonical English names, shortcuts.
NON_ARTICLE_NAMESPACES = frozenset(
    {
        "medya",
        "özel",
        "tartışma",
        "kullanıcı",
        "kullanıcı mesaj",
        "vikipedi",
        "vikipedi tartışma",
        "dosya",
        "dosya tartışma",
        "mediawiki",
        "mediawiki tartışma",
        "şablon",
        "şablon tartışma",
        "yardım",
        "yardım tartışma",
        "kategori",
        "kategori tartışma",
        "portal",
        "portal tartışma",
        "modül",
        "modül tartışma",
        "taslak",
        "taslak tartışma",
        "vp",
        "wp",
        "media",
        "special",
        "talk",
        "user",
        "user talk",
        "wikipedia",
        "wikipedia talk",
        "file",
        "file talk",
        "image",
        "mediawiki talk",
        "template",
        "template talk",
        "help",
        "help talk",
        "category",
        "category talk",
        "portal talk",
        "module",
        "module talk",
        "draft",
        "draft talk",
        "timedtext",
        "timedtext talk",
        "gadget",
        "gadget definition",
        "topic",
    }
)
SKIP_TITLES = frozenset({"Anasayfa", "Main_Page", "-", "Undefined", "Null"})

# Spikes whose title or Wikipedia description match these are left off the public page.
SENSITIVE_WORDS = ("porno", "pornograf", "erotik", "seks filmi", "xxx")


@dataclass(frozen=True)
class Settings:
    baseline_days: int = 28  # normal traffic = the previous four weeks
    history_days: int = 42  # length of the mini chart on the site
    min_views: int = 2_000  # ignore small pages
    min_ratio: float = 3.0  # at least 3x the usual daily views
    min_z: float = 5.0  # and a robust z-score of at least 5
    median_floor: float = 50.0  # keeps ratios finite for brand-new pages
    screen_ratio: float = 2.0  # looser first pass, before exact histories are fetched
    candidates: int = 40  # exact histories fetched per day
    max_spikes: int = 20  # spikes published per day
    min_mobile_share: float = 0.2  # below this, a spike looks like automated desktop traffic

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)
