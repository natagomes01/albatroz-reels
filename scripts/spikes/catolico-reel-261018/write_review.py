import json, sys
from pathlib import Path
from shorts.broll.model import validate_moments
job = Path(sys.argv[1])
n = len(json.load(open(job / "words.json"))["words"])
C = "https://commons.wikimedia.org/wiki/File:"
M = [  # id, first, last, file, w, h, title, author, license, page
 ("m1", 55, 67, "own-tabernaculo-codex-amiatinus-3.jpg", 4096, 2843, "Codex Amiatinus (c. 700 a 716), Biblioteca Medicea Laurenziana", "Rémi Mathis", "CC BY-SA 4.0", C+"Codex_Amiatinus_01.jpg", "a Igreja preservou e traduziu o texto"),
 ("m2", 116, 129, "own-arca-germigny-des-pres-2.jpg", 4096, 2730, "Mosaico de Germigny-des-Prés (806), a Arca e os querubins", "GFreihalter", "CC BY-SA 3.0", C+"Germigny-des-Pr%C3%A9s_%C3%89glise_de_la_Tr%C3%A8s-Sainte-Trinit%C3%A9_Mosa%C3%AFque_909.jpg", "Deus manda construir imagens"),
 ("m3", 152, 165, "own-capa-templo-salomao-chipiez.jpg", 3267, 4096, "O Templo de Jerusalém, restituição de Charles Chipiez (1887)", "Charles Chipiez", "Public domain", C+"Histoire_de_l%27art_dans_l%27antiquite._T._4_1887_(143262039).jpg", "1Cr 28,19: escrito pela mão do Senhor, cada detalhe do templo"),
 ("m5", 228, 237, "own-querubins-arca-gunst-1.jpg", 2708, 4096, "A Arca da Aliança com os querubins, gravura atribuída a P. S. van Gunst", "Philip De Vere", "CC BY-SA 3.0", C+"The_Phillip_Medhurst_Picture_Torah_480._The_ark_of_the_covenant._Exodus_cap_39_v_35._Gunst.jpg", "onde Deus mandou fazer imagens"),
 ("m6", 238, 251, "own-templo-fouquet-pompeu-2.jpg", 2880, 4096, "Pompeu no Templo de Jerusalém, Jean Fouquet (c. 1470 a 1475), BnF", "Jean Fouquet", "Public domain", C+"Flavius_Jos%C3%A8phe,_Les_Antiquit%C3%A9s_juda%C3%AFques.pdf", "imagens no templo, lugar sagrado de culto"),
 ("m7", 338, 349, "own-arca-germigny-des-pres-1.jpg", 4096, 3071, "Mosaico da abside de Germigny-des-Prés (806)", "Willyman", "CC BY-SA 4.0", C+"Mosaik_eines_K%C3%BCnstlers_aus_Ravenna_in_der_Ostabside_von_Germigny-des-Pr%C3%A9s_aus_130.000_Glassteinen.jpg", "enfeitar os seus templos com imagens sagradas"),
]
moments = [{"id": i, "origin": "owner", "first": a, "last": b, "layout": "full", "fit": "cover",
            "pan": "ltr" if w / h > 1080 / 1920 else "ttb", "focus": [0.5, 0.5], "terms": [], "note": note,
            "pick": {"source": "own", "kind": "image", "file": f, "id": f, "w": w, "h": h, "duration": None,
                     "download_url": "", "title": t, "author": au, "license": lic, "license_url": "", "page_url": pg}}
           for i, a, b, f, w, h, t, au, lic, pg, note in M]
moments = validate_moments(moments, n)
review = {"decisions": {"a931c03": {"status": "approved", "broll": moments,
                                    "word_fixes": {"17": "Imagens..."}}},
          "dereverb": 0}
out = job / "review.json"
assert not out.exists()
json.dump(review, open(out, "w"), ensure_ascii=False, indent=1)
print("ok", len(moments))
