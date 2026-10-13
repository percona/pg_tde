ALBUMS = [
    ("Graindelavoix", "Jisquin The Undead", "2021-06-12"),
    ("Graindelavoix", "Tenebrae Responsoria - Carlo Gesualdo", "2019-08-06"),
    ("Graindelavoix", "Cypriot Vespers", "2015-12-20"),
    ("John Coltrane", "Blue Train", "1957-09-15"),
    (
        "V/A Analog Africa",
        "Space Echo - The Mystery Behind the Cosmic Sound of Cabo Verde Finally Revealed",
        "2016-05-27",
    ),
    ("Incapacitants", "As Loud As Possible", "2022-09-15"),
    ("Chris Corsano & Bill Orcutt", "Made Out Of Sound", "2021-03-26"),
    (
        "J\xfcrg Frey (Quatuor Bozzini / Konus Quartett)",
        "Continuit\u200b\xe9\u200b, fragilit\u200b\xe9\u200b, r\u200b\xe9\u200bsonance",
        "2023-04-01",
    ),
    ("clipping.", "Visions of Bodies Being Burned", "2020-10-23"),
    ("clipping.", "There Existed an Addiction to Blood", "2019-10-19"),
    ("Autechre", "elseq 1–5", "2016-05-19"),
    ("Decapitated", "Winds of Creation", "2000-04-17"),
    ("Ulthar", "Anthronomicon", "2023-02-17"),
    ("Τζίμης Πανούσης", "Κάγκελα Παντού", "1986-01-01"),
    ("Воплі Відоплясова", "Музіка", "1997-01-01"),
]


def _rows(node):
    return node.safe_sql("SELECT id, artist, title, released::text FROM albums ORDER BY id")


def test_insert_update_delete(tde_node_db):
    node = tde_node_db
    node.safe_sql("""
        CREATE TABLE albums (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            artist VARCHAR(256),
            title TEXT NOT NULL,
            released DATE NOT NULL
        ) USING tde_heap
    """)
    for a in ALBUMS:
        node.safe_sql("INSERT INTO albums (artist, title, released) VALUES ($1, $2, $3)", a)
    expected = {str(i): list(a) for i, a in enumerate(ALBUMS, 1)}
    assert _rows(node) == [[k, *v] for k, v in expected.items()]

    node.safe_sql("DELETE FROM albums WHERE id % 4 = 0")
    expected = {k: v for k, v in expected.items() if int(k) % 4}
    assert _rows(node) == [[k, *v] for k, v in expected.items()]

    title = "Jisquin The Undead: Laments, Deplorations and Dances of Death"
    node.safe_sql(f"""
        UPDATE albums SET title = '{title}', released = '2021-10-01' WHERE id = 1;
        UPDATE albums SET released = '2020-04-01' WHERE id = 2;
    """)
    expected["1"] = [expected["1"][0], title, "2021-10-01"]
    expected["2"] = [*expected["2"][:2], "2020-04-01"]
    assert _rows(node) == [[k, *v] for k, v in expected.items()]


def test_temp_table(tde_node_db):
    node = tde_node_db
    node.safe_sql("""
        CREATE TEMPORARY TABLE animals (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            type TEXT UNIQUE,
            num INT
        ) USING tde_heap;
        INSERT INTO animals (type, num) VALUES ('cows', 3), ('pigs', 11);
    """)
    assert node.safe_sql("SELECT id, type, num FROM animals ORDER BY id") == [["1", "cows", "3"], ["2", "pigs", "11"]]
    node.safe_sql("DROP TABLE animals")
