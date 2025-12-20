import streamlit as st
from SPARQLWrapper import SPARQLWrapper, JSON
import ssl
from collections import defaultdict
import json
import os
import requests # NÉCESSAIRE POUR COMMONS

# --- 1. CONFIGURATION ---
DB_FILE = "mes_images_locales.json"
IMG_FOLDER = "images"

if not os.path.exists(IMG_FOLDER):
    os.makedirs(IMG_FOLDER)

def load_local_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_local_entry(wikidata_id, image_path):
    db = load_local_db()
    db[wikidata_id] = image_path
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

# --- 2. FIX SSL ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- 3. FONCTION MAGIQUE : COMMONS ---
@st.cache_data
def get_commons_images(category_name, limit=3):
    """
    Va chercher directement des images dans la catégorie Wikimedia Commons de l'artiste
    si Wikidata ne donne rien.
    """
    if not category_name:
        return []
    
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "categorymembers",
        "gcmtitle": f"Category:{category_name}",
        "gcmtype": "file",
        "gcmlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json"
    }
    
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        images = []
        if "query" in data and "pages" in data["query"]:
            for page_id, page_data in data["query"]["pages"].items():
                if "imageinfo" in page_data:
                    img_url = page_data["imageinfo"][0]["url"]
                    # On évite les fichiers .pdf ou .tif trop lourds
                    if img_url.lower().endswith(('.jpg', '.jpeg', '.png')):
                        images.append(img_url)
        return images
    except:
        return []

# --- 4. CSS ---
st.set_page_config(page_title="Art Explorer Ultra", layout="wide")
st.markdown("""
<style>
    .img-container { border: 1px solid #ddd; padding: 10px; border-radius: 8px; background-color: white; margin-bottom: 20px; }
    .caption { font-size: 0.9em; font-weight: bold; color: #222; margin-top:5px; line-height: 1.2; }
    .role-tag { font-size: 0.7em; color: #fff; background-color: #666; padding: 1px 4px; border-radius: 3px; }
    
    /* BOUTONS SOURCES */
    .btn-source {
        text-decoration: none; display: inline-block; padding: 2px 6px; border-radius: 3px; 
        font-size: 0.65em; font-weight: bold; margin-right: 3px; opacity: 0.9;
    }
    .wiki { background-color: #f0f0f0; color: #333; border: 1px solid #ccc; }
    .commons { background-color: #eaecf0; color: #333; border: 1px solid #c8ccd1; }
    .getty { background-color: #0b2e59; color: #fff; }
    .rkd { background-color: #f36f21; color: #fff; }
    .wga { background-color: #5d4037; color: #fff; }
    
    .from-commons {
        font-size: 0.7em; color: #e67e22; font-style: italic; margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)

# --- 5. SPARQL PRINCIPAL ---
@st.cache_data
def get_artists_with_commons(year_start, year_end, city_name=None, max_per_artist=3, limit=3000):
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql", agent="MonAppArt_Commons/1.0")
    sparql.setTimeout(60)
    
    city_filter = ""
    if city_name and city_name.strip() != "":
        city_filter = f"""
        {{ ?artist wdt:P937 ?loc. }} UNION {{ ?artist wdt:P19 ?loc. }} UNION {{ ?artist wdt:P20 ?loc. }}
        ?loc rdfs:label ?locLabel.
        FILTER(REGEX(?locLabel, "{city_name}", "i") && lang(?locLabel) = "fr")
        """

    query = f"""
    SELECT DISTINCT ?artist ?artistLabel ?birthDate ?deathDate ?work ?workLabel ?image ?workDate ?roleLabel ?ulanId ?rkdId ?wgaId ?commonsCat
    WHERE {{
      hint:Query hint:optimizer "None".
      
      VALUES ?role {{ wd:Q1028181 wd:Q15953503 wd:Q1580177 wd:Q3393341 wd:Q36180 }}
      ?artist wdt:P106 ?role.
      
      ?artist wdt:P569 ?birthDate.
      FILTER(?birthDate >= "{year_start}-01-01"^^xsd:dateTime && ?birthDate <= "{year_end}-12-31"^^xsd:dateTime)
      {city_filter}
      
      OPTIONAL {{ ?artist wdt:P570 ?deathDate. }}
      
      # LIENS EXTERNES
      OPTIONAL {{ ?artist wdt:P245 ?ulanId. }}
      OPTIONAL {{ ?artist wdt:P650 ?rkdId. }}
      OPTIONAL {{ ?artist wdt:P6516 ?wgaId. }}
      OPTIONAL {{ ?artist wdt:P373 ?commonsCat. }} # ON RÉCUPÈRE LA CATÉGORIE COMMONS
      
      # ŒUVRES (Optionnelles)
      OPTIONAL {{
        ?work wdt:P170 ?artist.
        OPTIONAL {{ ?work wdt:P18 ?image. }}
        OPTIONAL {{ ?work wdt:P571 ?workDate. }}
      }}
      
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
    }}
    LIMIT {limit}
    """
    
    try:
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
    except Exception as e:
        print(f"Erreur SPARQL: {e}")
        return []

    artists_map = {}
    local_db = load_local_db()

    for r in results["results"]["bindings"]:
        artist_id = r["artist"]["value"].split("/")[-1]
        
        if artist_id not in artists_map:
            b_date = r["birthDate"]["value"][:4]
            d_date = r["deathDate"]["value"][:4] if "deathDate" in r else ""
            
            artists_map[artist_id] = {
                "name": r.get("artistLabel", {}).get("value", "Anonyme"),
                "dates": f"{b_date}-{d_date}" if d_date else f"né en {b_date}",
                "role": r.get("roleLabel", {}).get("value", "Artiste"),
                "url": r["artist"]["value"],
                "ulan": r.get("ulanId", {}).get("value", None),
                "rkd": r.get("rkdId", {}).get("value", None),
                "wga": r.get("wgaId", {}).get("value", None),
                "commons": r.get("commonsCat", {}).get("value", None), # La clé magique
                "works": []
            }
        
        if "work" in r:
            wid = r["work"]["value"].split("/")[-1]
            if wid in local_db:
                img = local_db[wid]
                itype = "local"
            elif "image" in r:
                raw = r["image"]["value"].replace("http://", "https://")
                img = raw + "?width=400" if "Special:FilePath" in raw else raw
                itype = "web"
            else:
                img = None # On ne met pas de placeholder tout de suite
                itype = "none"

            if img: # On ne stocke que si on a une image valide pour l'instant
                artists_map[artist_id]["works"].append({
                    "id": wid,
                    "title": r.get("workLabel", {}).get("value", "Sans titre"),
                    "date": r["workDate"]["value"][:4] if "workDate" in r else "n.d.",
                    "image": img,
                    "type": itype
                })

    # FORMATAGE & ENRICHISSEMENT COMMONS
    display_list = []
    sorted_artists = sorted(artists_map.values(), key=lambda x: x['dates'])
    
    for artist in sorted_artists:
        # LIENS HTML
        links = f'<a href="{artist["url"]}" target="_blank" class="btn-source wiki">Wiki</a>'
        if artist["commons"]:
             links += f'<a href="https://commons.wikimedia.org/wiki/Category:{artist["commons"]}" target="_blank" class="btn-source commons">Commons</a>'
        if artist["ulan"]: links += f'<a href="https://www.getty.edu/vow/ULANFullDisplay?find=&role=&nation=&subjectid={artist["ulan"]}" target="_blank" class="btn-source getty">Getty</a>'
        if artist["rkd"]: links += f'<a href="https://rkd.nl/en/explore/artists/{artist["rkd"]}" target="_blank" class="btn-source rkd">RKD</a>'
        if artist["wga"]: links += f'<a href="https://www.wga.hu/{artist["wga"]}" target="_blank" class="btn-source wga">WGA</a>'

        # STRATÉGIE D'AFFICHAGE IMAGES
        # 1. On a des œuvres Wikidata avec images ?
        valid_works = artist["works"]
        
        # 2. Si on n'en a pas assez (< max_per_artist), on va chercher dans Commons !
        if len(valid_works) < max_per_artist and artist["commons"]:
            needed = max_per_artist - len(valid_works)
            commons_imgs = get_commons_images(artist["commons"], limit=needed)
            
            for c_img in commons_imgs:
                valid_works.append({
                    "id": "commons_img",
                    "title": "Via Wikimedia Commons",
                    "date": "",
                    "image": c_img,
                    "type": "commons_api"
                })
        
        # 3. Si toujours rien, on met l'icône placeholder
        if not valid_works:
            display_list.append({
                "artist_name": artist["name"],
                "artist_dates": artist["dates"],
                "artist_role": artist["role"],
                "links": links,
                "work_title": "Pas d'image trouvée",
                "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/16/Former_man_icon.svg/200px-Former_man_icon.svg.png",
                "type": "artist_only",
                "source_label": ""
            })
        else:
            for i, w in enumerate(valid_works):
                if i >= max_per_artist: break
                
                # Petit label pour dire d'où vient l'image
                src_label = ""
                if w['type'] == 'commons_api':
                    src_label = "🌍 Image Commons (Non liée)"
                
                display_list.append({
                    "artist_name": artist["name"],
                    "artist_dates": artist["dates"],
                    "artist_role": artist["role"],
                    "links": links,
                    "work_title": w["title"],
                    "work_date": w["date"],
                    "image": w["image"],
                    "type": w["type"],
                    "source_label": src_label,
                    "id": w.get("id", "unknown")
                })

    return display_list

# --- INTERFACE ---
st.sidebar.title("🚀 Art Explorer Ultra")

years = st.sidebar.slider("Année de Naissance", 1300, 1900, (1480, 1500))
city = st.sidebar.text_input("Ville (Naissance/Mort/Travail)", "Florence")
max_per_artist = st.sidebar.slider("Images par artiste", 1, 6, 3)

if st.button("🔎 Lancer la recherche étendue", type="primary"):
    st.session_state.data = get_artists_with_commons(years[0], years[1], city, max_per_artist)

if 'data' in st.session_state:
    data = st.session_state.data
    st.success(f"{len(set(d['artist_name'] for d in data))} artistes trouvés.")
    
    cols = st.columns(5)
    for i, item in enumerate(data):
        with cols[i % 5]:
            with st.container(border=True):
                # IMAGE
                st.image(item['image'], use_container_width=True)
                
                # Source Label (si Commons)
                if item['source_label']:
                    st.markdown(f"<div class='from-commons'>{item['source_label']}</div>", unsafe_allow_html=True)

                st.markdown(f"<div class='caption'>{item['artist_name']}</div>", unsafe_allow_html=True)
                st.markdown(f"<span class='role-tag'>{item['artist_role']}</span>", unsafe_allow_html=True)
                st.markdown(f"<div class='sub-caption'>{item['artist_dates']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='link-row'>{item['links']}</div>", unsafe_allow_html=True)
                
                if item['type'] != 'artist_only' and item['type'] != 'commons_api':
                    st.caption(f"_{item['work_title']}_ ({item['work_date']})")
                
                # Upload seulement si pas d'image du tout
                if item['type'] == 'artist_only':
                     with st.expander("➕"):
                            upl = st.file_uploader("", type=['jpg','png'], key=f"u_{i}", label_visibility="collapsed")