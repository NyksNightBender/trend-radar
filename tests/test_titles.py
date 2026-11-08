from trend_radar.titles import display, is_article, is_sensitive, wiki_url


def test_articles_and_non_articles() -> None:
    assert is_article("Mustafa_Kemal_Atatürk")
    assert is_article("Star_Wars:_Yeni_Bir_Umut")  # a colon that is not a namespace
    for title in (
        "Anasayfa",
        "Özel:Ara",
        "Kategori:Türkiye",
        "Vikipedi:Hakkında",
        "-",
        "Special:Search",
        "Dosya:Logo.png",
        "Şablon:Bilgi_kutusu",
    ):
        assert not is_article(title), title


def test_display_and_url() -> None:
    assert display("Ege_Üniversitesi") == "Ege Üniversitesi"
    assert wiki_url("Ege Üniversitesi") == "https://tr.wikipedia.org/wiki/Ege_%C3%9Cniversitesi"
    assert wiki_url("AC/DC") == "https://tr.wikipedia.org/wiki/AC%2FDC"


def test_sensitive() -> None:
    assert is_sensitive("X", "Amerikalı pornografik film oyuncusu")
    assert not is_sensitive("Galatasaray", "Türk spor kulübü")
    assert not is_sensitive("Y", None)
