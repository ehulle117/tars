"""Starter recipes from the Modern Meadmaking wiki (https://wiki.meadtools.com/en/recipes).
Ingredients and targets only; methods are short summaries — follow the link for the full write-up."""

WIKI = "https://wiki.meadtools.com/en/recipes/"
H = 35  # honey ppg
JUICE = 50  # apple juice/cider, points per gallon

# (kind, name, amount, unit, ppg)
RECIPES = [
    dict(name="Basic Traditional", style="traditional", volume_gal=1, yeast="Safale US-05 (3-5 g)", n_need="medium",
         target_og=1.110, target_fg=1.012, target_fg_max=1.022, url="beginner/0001",
         notes="Sweet traditional. Honey + water to 1 gal, pitch dry yeast, add DAP and boiled bread yeast up front, "
               "shake well. Ferment 60-75°F. Rack when done, optional Campden tablet, bottle when clear. "
               "US-05's low tolerance leaves it sweet; a 14% wine yeast will finish drier.",
         ings=[("honey", "orange blossom", 3.2, "lb", H), ("nutrient", "DAP", 1, "tsp", None),
               ("nutrient", "boiled bread yeast", 1, "tsp", None), ("stabilizer", "Campden tablet (post-ferment)", 1, "each", None)]),
    dict(name="Basic Metheglin", style="metheglin", volume_gal=1, yeast="Safale US-05 (3-5 g)", n_need="medium",
         target_og=1.110, target_fg=1.012, target_fg_max=1.022, url="beginner/0002",
         notes="Basic Traditional plus spices. Simmer the cinnamon and vanilla in a cup of water 10 min to sanitize, "
               "add them with that water after pitching. Same nutrients and timeline as the traditional.",
         ings=[("honey", "base honey", 3.2, "lb", H), ("spice", "cinnamon stick (~3 in)", 1, "each", None),
               ("spice", "vanilla bean (~4 in)", 1, "each", None), ("nutrient", "DAP", 1, "tsp", None),
               ("nutrient", "boiled bread yeast", 1, "tsp", None), ("stabilizer", "Campden tablet (post-ferment)", 1, "each", None)]),
    dict(name="Basic Melomel", style="melomel", volume_gal=1, yeast="Lalvin 71B-1122 (5 g)", n_need="low",
         target_og=1.100, target_fg=1.000, target_fg_max=1.025, url="beginner/0003",
         notes="Freeze/thaw fruit. Rehydrate yeast in GoFerm. 1 lb raspberries in primary; Fermaid O after lag, "
               "Fermaid K + DAP split at 48h and 72h; punch fruit down daily for 5 days. After ~2 weeks rack onto "
               "remaining raspberries, blueberries and split vanilla pod for 2 weeks, then stabilize/backsweeten and clear.",
         ings=[("honey", "wildflower or orange blossom", 3, "lb", H), ("fruit", "raspberries (primary)", 1, "lb", 4),
               ("fruit", "raspberries (secondary)", 0.5, "lb", None), ("fruit", "blueberries (secondary)", 0.5, "lb", None),
               ("spice", "vanilla pod (secondary)", 1, "each", None), ("nutrient", "GoFerm PE", 6.25, "g", None),
               ("nutrient", "Fermaid O", 1.7, "g", None), ("nutrient", "Fermaid K", 1.9, "g", None), ("nutrient", "DAP", 1.1, "g", None)]),
    dict(name="Basic Cyser", style="cyser", volume_gal=1, yeast="Safale US-05 (3-5 g)", n_need="medium",
         target_og=1.126, target_fg=1.030, target_fg_max=1.040, url="beginner/0004",
         notes="Honey topped up to 1 gal with preservative-free apple juice or cider. Same nutrients and process as "
               "Basic Traditional. Finishes sweet with US-05.",
         ings=[("honey", "base honey", 2, "lb", H), ("fruit", "apple juice, no preservatives", 1, "gal", JUICE),
               ("nutrient", "DAP", 1, "tsp", None), ("nutrient", "boiled bread yeast", 1, "tsp", None),
               ("stabilizer", "Campden tablet (post-ferment)", 1, "each", None)]),
    dict(name="Traditional (5 gal)", style="traditional", volume_gal=5, yeast="SafAle US-05 (11.5 g)", n_need="medium",
         target_og=1.075, target_fg=1.000, target_fg_max=1.012, url="traditionals/0001",
         notes="Dry to semi-sweet still traditional; honey and yeast are the only flavor, so use a good honey. "
               "Rehydrate in GoFerm; staggered Fermaid O/K + DAP.",
         ings=[("honey", "good varietal", 10.5, "lb", H), ("nutrient", "GoFerm PE", 14.4, "g", None),
               ("nutrient", "Fermaid O", 8.5, "g", None), ("nutrient", "Fermaid K", 9.0, "g", None), ("nutrient", "DAP", 5, "g", None)]),
    dict(name="Chai Metheglin (5 gal)", style="metheglin", volume_gal=5, yeast="Lalvin D-47 (5 g)", n_need="low",
         target_og=1.108, target_fg=1.000, target_fg_max=1.012, url="metheglins/0002",
         notes="Fermented chai: wildflower honey with a chai tea blend (black tea, cinnamon, cardamom, pepper). "
               "See the wiki for tea timing.",
         ings=[("honey", "wildflower", 15, "lb", H), ("spice", "chai tea blend", 2, "oz", None),
               ("nutrient", "Fermaid O", 8.5, "g", None), ("nutrient", "Fermaid K", 9.0, "g", None)]),
    dict(name="Cherry Melomel (5 gal)", style="melomel", volume_gal=5, yeast="Lalvin 71B or RC-212 (10 g)", n_need="low",
         target_og=1.138, target_fg=1.020, target_fg_max=1.030, url="melomels/0001",
         notes="Sweet still melomel on whole tart cherries with pits, plus pectic enzyme. Rehydrate in GoFerm; "
               "staggered Fermaid O/K + DAP. Fruit sugar varies, so trust your measured OG over the estimate.",
         ings=[("honey", "good honey", 14, "lb", H), ("fruit", "tart cherries, whole", 15, "lb", 5),
               ("other", "pectic enzyme", 2.5, "tsp", None), ("nutrient", "GoFerm PE", 12.5, "g", None),
               ("nutrient", "Fermaid O", 8.5, "g", None), ("nutrient", "Fermaid K", 9.5, "g", None), ("nutrient", "DAP", 13.8, "g", None)]),
    dict(name="Standard Cyser (5 gal)", style="cyser", volume_gal=5, yeast="Lalvin QA23 (10 g)", n_need="low",
         target_og=1.107, target_fg=0.995, target_fg_max=1.000, url="cysers/0001",
         notes="Dry cyser: honey in fresh-pressed, preservative-free cider. Rehydrate in GoFerm; staggered Fermaid O/K + DAP.",
         ings=[("honey", "base honey", 9, "lb", H), ("fruit", "fresh apple cider", 4.25, "gal", JUICE),
               ("nutrient", "GoFerm PE", 12.5, "g", None), ("nutrient", "Fermaid O", 8.5, "g", None),
               ("nutrient", "Fermaid K", 9.5, "g", None), ("nutrient", "DAP", 2.7, "g", None)]),
    dict(name="Rhodomel (5 gal)", style="metheglin", volume_gal=5, yeast="Lalvin 71B (5 g)", n_need="low",
         target_og=1.093, target_fg=1.000, target_fg_max=1.012, url="metheglins/0001",
         notes="Dry rose mead with spices: wildflower honey, rose petals (food-safe, no pesticides), Saaz hops "
               "bagged in a short boil, grated ginger, cinnamon and medium-toast American oak. See the wiki for timing.",
         ings=[("honey", "wildflower", 13, "lb", H), ("spice", "rose petals, food-safe", 1, "lb", None),
               ("spice", "Saaz hops", 2, "oz", None), ("spice", "ginger, grated", 0.5, "lb", None),
               ("spice", "cinnamon stick", 2, "each", None), ("oak", "med toast American oak spiral", 2, "each", None),
               ("nutrient", "Fermaid O", 8.5, "g", None), ("nutrient", "Fermaid K", 9.0, "g", None)]),
    dict(name="Blackberry Orange Blossom Melomel (5 gal)", style="melomel", volume_gal=5, yeast="Lalvin 71B or RC-212 (10 g)",
         n_need="low", target_og=1.128, target_fg=1.010, target_fg_max=1.020, url="melomels/0002",
         notes="Sweet still melomel: orange blossom honey, blackberries (raspberries work too) and 10-15 oranges, "
               "with pectic enzyme. Rehydrate in GoFerm; staggered Fermaid O/K + DAP. Fruit sugar varies, so trust "
               "your measured OG over the estimate.",
         ings=[("honey", "orange blossom", 14, "lb", H), ("fruit", "blackberries", 20, "lb", 4),
               ("fruit", "oranges", 12, "each", None), ("other", "pectic enzyme", 2.5, "tsp", None),
               ("nutrient", "GoFerm PE", 12.5, "g", None), ("nutrient", "Fermaid O", 8.5, "g", None),
               ("nutrient", "Fermaid K", 9.5, "g", None), ("nutrient", "DAP", 11.7, "g", None)]),
    dict(name="Smoked Capsicumel (5 gal)", style="capsicumel", volume_gal=5, yeast="Lalvin D-47 or Red Star Pasteur Champagne (10 g)",
         n_need="low", target_og=1.110, target_fg=1.000, target_fg_max=1.030, url="capsicumels/0001",
         notes="Spicy pepper mead on mesquite honey with jalapeños and cayenne (seeds and pith removed); add habaneros "
               "to taste for more heat. Oaked and smoked per the wiki write-up. Staggered Fermaid O/K + DAP.",
         ings=[("honey", "mesquite", 15, "lb", H), ("water", "to 5 gal (~3.75 gal)", 3.75, "gal", None),
               ("spice", "jalapeños, seeded", 15, "oz", None), ("spice", "cayenne, seeded", 5, "oz", None),
               ("nutrient", "Fermaid O", 8.5, "g", None), ("nutrient", "Fermaid K", 8.5, "g", None), ("nutrient", "DAP", 5.5, "g", None)]),
    dict(name="Sparkling Hydromel (5 gal)", style="hydromel", volume_gal=5, yeast="SafAle US-05 (11.5 g)", n_need="medium",
         target_og=1.060, target_fg=1.012, target_fg_max=None, url="hydromels/0001",
         notes="Semi-sweet sparkling traditional, carbonated to 2.5 volumes. Ferment 8.5 lb of a good honey (tupelo, "
               "orange blossom, meadowfoam, fireweed); stabilize, then backsweeten with the other 2 lb. "
               "Bottle conditioning isn't possible after stabilizing, so see the wiki for how to carbonate.",
         ings=[("honey", "good varietal (fermentation)", 8.5, "lb", H), ("honey", "same honey (backsweetening)", 2, "lb", None),
               ("nutrient", "GoFerm PE", 14.4, "g", None), ("nutrient", "Fermaid O", 8.5, "g", None),
               ("nutrient", "Fermaid K", 9.0, "g", None), ("stabilizer", "potassium metabisulfite", 1.0, "g", None),
               ("stabilizer", "potassium sorbate", 3.75, "g", None)]),
    dict(name="Bochet (5 gal)", style="bochet", volume_gal=5, yeast="Lalvin EC-1118 (10 g)", n_need="low",
         target_og=1.129, target_fg=1.000, target_fg_max=1.012, url="other/0001",
         notes="Mead from caramelized (cooked) wildflower honey, aged on medium-toast American oak. See the wiki for "
               "how to caramelize safely. Rehydrate in GoFerm; staggered Fermaid O/K + DAP.",
         ings=[("honey", "wildflower, caramelized", 18, "lb", H), ("oak", "med toast American oak spiral", 2, "each", None),
               ("nutrient", "GoFerm PE", 12.0, "g", None), ("nutrient", "Fermaid O", 8.5, "g", None),
               ("nutrient", "Fermaid K", 9.0, "g", None), ("nutrient", "DAP", 16.0, "g", None)]),
    dict(name="Braggot (5 gal)", style="braggot", volume_gal=5, yeast="GV12 or Nottingham ale yeast (10 g)", n_need="medium",
         target_og=1.072, target_fg=1.000, target_fg_max=None, url="other/0002",
         notes="Carbonated spiced braggot: half honey, half amber malt, with lemon juice and zest, cranberries "
               "(pectinase first) and Cascade + Golding hops. Malt PPG assumes liquid extract (~36); use ~44 for dry extract.",
         ings=[("honey", "wildflower", 5, "lb", H), ("other", "amber malt extract", 5, "lb", 36),
               ("fruit", "lemons, juice and zest", 7, "each", None), ("fruit", "cranberries", 5, "lb", None),
               ("spice", "Cascade hops", 2, "oz", None), ("spice", "Golding hops", 2, "oz", None),
               ("nutrient", "GoFerm PE", 12.5, "g", None), ("nutrient", "Fermaid O", 8.5, "g", None),
               ("nutrient", "Fermaid K", 9.5, "g", None), ("nutrient", "DAP", 4.2, "g", None)]),
]


def run(con):
    """Add any recipe not seeded before. Remembers what it added, so recipes you delete stay deleted."""
    con.execute("CREATE TABLE IF NOT EXISTS seeded (url TEXT PRIMARY KEY)")
    done = {row[0] for row in con.execute("SELECT url FROM seeded")}
    for r in RECIPES:
        url = WIKI + r["url"]
        if url in done:
            continue
        con.execute("INSERT INTO seeded (url) VALUES (?)", (url,))
        # databases seeded before this table existed: don't duplicate what's already there
        if con.execute("SELECT 1 FROM batch WHERE status='recipe' AND source_url=?", (url,)).fetchone():
            continue
        bid = con.execute(
            """INSERT INTO batch (name, status, style, volume_gal, yeast, n_need, nutrient_protocol,
                                  target_og, target_fg, target_fg_max, source_url, notes)
               VALUES (?, 'recipe', ?, ?, ?, ?, 'recipe', ?, ?, ?, ?, ?)""",
            (r["name"], r["style"], r["volume_gal"], r["yeast"], r["n_need"], r["target_og"],
             r["target_fg"], r["target_fg_max"], url, r["notes"])).lastrowid
        con.executemany("INSERT INTO ingredient (batch_id, kind, name, amount, unit, ppg) VALUES (?,?,?,?,?,?)",
                        [(bid, *i) for i in r["ings"]])
