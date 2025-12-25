"""
Hent skiløyper fra OpenStreetMap (OSM)
Basert på: https://wiki.openstreetmap.org/wiki/No:Skiløyper

OSM-tagger for skiløyper:
- piste:type=nordic (langrennsløyper)
- route=piste (skiløyperuter)
- piste:grooming=* (preparering)
- piste:difficulty=* (vanskelighetsgrad)
"""

import requests
import json
import folium
from folium import FeatureGroup
from datetime import datetime
from pathlib import Path

# Prøv å importere geopandas for punkt-i-polygon (valgfritt)
try:
    import geopandas as gpd
    from shapely.geometry import Point, shape
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    print("⚠️  geopandas ikke tilgjengelig - bruker fallback til Nominatim")
    print("   Installer med: pip install geopandas shapely")
    print()


def hent_skiløyper_osm(bbox, kommuner_gdf=None, timeout=180):
    """
    Hent skiløyper fra OpenStreetMap via Overpass API
    
    Args:
        bbox: Bounding box som (min_lat, min_lon, max_lat, max_lon)
        kommuner_gdf: GeoDataFrame med kommunegrenser for rask kommune-lookup
        timeout: Timeout i sekunder for API-kallet
    
    Returns:
        GeoJSON FeatureCollection med skiløyper
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    
    # Overpass QL query for skiløyper
    # Henter ways (linjer) med piste:type=nordic eller route=piste
    # Ekskluderer backcountry løyper
    overpass_query = f"""
    [out:json][timeout:{timeout}];
    (
      // Langrennsløyper (ikke backcountry)
      way["piste:type"="nordic"]["piste:grooming"!="backcountry"]({min_lat},{min_lon},{max_lat},{max_lon});
      
      // Skiløyperuter (ikke backcountry)
      way["route"="piste"]["piste:grooming"!="backcountry"]({min_lat},{min_lon},{max_lat},{max_lon});
      
      // Alternative tagger (ikke backcountry)
      way["highway"="path"]["piste:type"="nordic"]["piste:grooming"!="backcountry"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    out body;
    >;
    out skel qt;
    """
    
    print(f"Henter skiløyper fra OSM...")
    print(f"Område: {min_lat:.4f}°N - {max_lat:.4f}°N, {min_lon:.4f}°E - {max_lon:.4f}°E")
    
    overpass_url = "https://overpass-api.de/api/interpreter"
    
    try:
        response = requests.post(overpass_url, data={'data': overpass_query}, timeout=timeout)
        response.raise_for_status()
        osm_data = response.json()
        
        # Konverter OSM data til GeoJSON med kommune-informasjon
        geojson = osm_til_geojson(osm_data, kommuner_gdf)
        
        feature_count = len(geojson['features'])
        print(f"✓ Hentet {feature_count} skiløyper fra OSM")
        
        return geojson
        
    except requests.exceptions.Timeout:
        print(f"✗ Timeout etter {timeout} sekunder")
        print("  Prøv å redusere området eller øke timeout")
        return None
    except Exception as e:
        print(f"✗ Feil ved henting: {e}")
        return None


def last_kommunegrenser(filepath='kommunegrenser_norge.geojson'):
    """
    Last inn kommunegrenser fra GeoJSON-fil for punkt-i-polygon lookup
    """
    if not GEOPANDAS_AVAILABLE:
        return None
    
    if not Path(filepath).exists():
        print(f"⚠️  Finner ikke {filepath}")
        print(f"   Kjør 'python last_ned_kommunegrenser.py' først")
        print(f"   Faller tilbake til Nominatim API\n")
        return None
    
    try:
        gdf = gpd.read_file(filepath)
        print(f"✓ Lastet {len(gdf)} kommuner fra {filepath}")
        return gdf
    except Exception as e:
        print(f"⚠️  Kunne ikke laste kommunegrenser: {e}")
        return None


def finn_kommune_fra_polygon(lat, lon, kommuner_gdf):
    """
    Finn kommune ved punkt-i-polygon test (rask, offline)
    """
    if kommuner_gdf is None:
        return None
    
    try:
        point = Point(lon, lat)
        matches = kommuner_gdf[kommuner_gdf.contains(point)]
        if not matches.empty:
            return matches.iloc[0]['kommune_navn']
    except:
        pass
    return None


def finn_kommune(lat, lon, timeout=10):
    """
    Finn kommune for et gitt koordinat ved hjelp av Nominatim reverse geocoding
    """
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'format': 'json',
            'addressdetails': 1,
            'zoom': 10
        }
        headers = {
            'User-Agent': 'SkiTrailMapper/1.0'
        }
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            # Prøv forskjellige felt for kommune
            kommune = address.get('municipality') or address.get('town') or address.get('city') or address.get('village')
            return kommune
    except:
        pass
    return 'Ukjent'


def osm_til_geojson(osm_data, kommuner_gdf=None):
    """
    Konverter OSM JSON til GeoJSON FeatureCollection med kommune-informasjon
    
    Args:
        osm_data: OSM data fra Overpass API
        kommuner_gdf: GeoDataFrame med kommunegrenser (valgfritt)
    """
    # Bygg en dict med noder (punkter)
    nodes = {}
    for element in osm_data.get('elements', []):
        if element['type'] == 'node':
            nodes[element['id']] = (element['lon'], element['lat'])
    
    # Cache for kommune-oppslag
    kommune_cache = {}
    use_polygon_method = kommuner_gdf is not None
    
    if use_polygon_method:
        print("  Bruker punkt-i-polygon metode (rask, offline)")
    else:
        print("  Bruker Nominatim API (tregere, krever internett)")
    
    # Bygg GeoJSON features fra ways (linjer)
    features = []
    processed = 0
    for element in osm_data.get('elements', []):
        if element['type'] == 'way' and 'nodes' in element:
            # Hent koordinater for alle noder i way
            coordinates = []
            for node_id in element['nodes']:
                if node_id in nodes:
                    coordinates.append(nodes[node_id])
            
            if len(coordinates) < 2:
                continue  # Trenger minst 2 punkter for en linje
            
            # Finn midtpunkt av løypa for kommune-oppslag
            mid_idx = len(coordinates) // 2
            mid_lon, mid_lat = coordinates[mid_idx]
            
            # Bygg properties fra tags
            tags = element.get('tags', {})
            
            # Prøv å finne kommune fra OSM tags først
            kommune = tags.get('is_in') or tags.get('addr:municipality')
            
            # Hvis ikke funnet, bruk punkt-i-polygon eller reverse geocoding
            if not kommune:
                cache_key = f"{mid_lat:.2f},{mid_lon:.2f}"
                if cache_key in kommune_cache:
                    kommune = kommune_cache[cache_key]
                else:
                    if use_polygon_method:
                        # Rask offline metode
                        kommune = finn_kommune_fra_polygon(mid_lat, mid_lon, kommuner_gdf)
                    
                    if not kommune:
                        # Fallback til Nominatim
                        kommune = finn_kommune(mid_lat, mid_lon)
                        import time
                        time.sleep(1)  # Rate limiting for Nominatim
                    
                    kommune_cache[cache_key] = kommune
            
            properties = {
                'osm_id': element['id'],
                'name': tags.get('name', 'Uten navn'),
                'piste_type': tags.get('piste:type', 'unknown'),
                'piste_grooming': tags.get('piste:grooming', 'unknown'),
                'piste_difficulty': tags.get('piste:difficulty', 'unknown'),
                'route': tags.get('route', ''),
                'operator': tags.get('operator', ''),
                'website': tags.get('website', ''),
                'description': tags.get('description', ''),
                'municipality': kommune or 'Ukjent',
            }
            
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'LineString',
                    'coordinates': coordinates
                },
                'properties': properties
            }
            features.append(feature)
            
            processed += 1
            if processed % 50 == 0:
                print(f"  Prosessert {processed} løyper...")
    
    return {
        'type': 'FeatureCollection',
        'features': features
    }


def vis_på_kart(geojson, output_file='skiløyper_osm_kart.html'):
    """
    Vis skiløyper på et interaktivt Folium-kart med kommune-filter
    """
    if not geojson or not geojson['features']:
        print("Ingen skiløyper å vise")
        return None
    
    features = geojson['features']
    print(f"\nLager kart med {len(features)} skiløyper...")
    
    # Finn sentrum av kartet
    all_coords = []
    for feature in features:
        coords = feature['geometry']['coordinates']
        all_coords.extend(coords)
    
    if not all_coords:
        print("Ingen koordinater funnet")
        return None
    
    center_lon = sum(c[0] for c in all_coords) / len(all_coords)
    center_lat = sum(c[1] for c in all_coords) / len(all_coords)
    
    # Samle alle unike kommuner
    municipalities = set()
    for feature in features:
        muni = feature['properties'].get('municipality', 'Ukjent')
        municipalities.add(muni)
    
    municipalities = sorted(list(municipalities))
    print(f"  Funnet løyper i {len(municipalities)} kommuner: {', '.join(municipalities[:5])}{'...' if len(municipalities) > 5 else ''}")
    
    # Opprett kart
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles='OpenStreetMap'
    )
    
    # Alle løyper vises i rød farge
    def get_color(properties):
        return 'red'
    
    # Opprett LayerGroups for hver kommune
    municipality_layers = {}
    for muni in municipalities:
        municipality_layers[muni] = FeatureGroup(name=muni)
    
    # Legg til skiløyper i riktig LayerGroup
    for feature in features:
        properties = feature['properties']
        muni = properties.get('municipality', 'Ukjent')
        
        # Bygg popup-tekst
        popup_html = f"""
        <div style="font-family: Arial; min-width: 200px;">
            <h4>{properties.get('name', 'Uten navn')}</h4>
            <table style="width:100%">
                <tr><td><b>Kommune:</b></td><td>{muni}</td></tr>
                <tr><td><b>Type:</b></td><td>{properties.get('piste_type', 'N/A')}</td></tr>
                <tr><td><b>Preparering:</b></td><td>{properties.get('piste_grooming', 'N/A')}</td></tr>
                <tr><td><b>Vanskelighet:</b></td><td>{properties.get('piste_difficulty', 'N/A')}</td></tr>
                <tr><td><b>Operatør:</b></td><td>{properties.get('operator', 'N/A')}</td></tr>
            </table>
        """
        
        if properties.get('website'):
            popup_html += f'<p><a href="{properties["website"]}" target="_blank">Nettside</a></p>'
        
        if properties.get('description'):
            popup_html += f'<p><i>{properties["description"]}</i></p>'
        
        popup_html += f'<p style="font-size:10px; color:#666;">OSM ID: {properties["osm_id"]}</p>'
        popup_html += "</div>"
        
        color = get_color(properties)
        
        folium.GeoJson(
            feature,
            style_function=lambda x, color=color: {
                'color': color,
                'weight': 4,
                'opacity': 0.8
            },
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(municipality_layers[muni])
    
    # Legg til alle LayerGroups til kartet
    for layer in municipality_layers.values():
        layer.add_to(m)
    
    # Legg til LayerControl for å vise/skjule kommuner
    folium.LayerControl(collapsed=False).add_to(m)
    
    # Legg til tegnforklaring
    legend_html = """
    <div style="position: fixed; 
                bottom: 50px; right: 50px; width: 220px; height: auto; 
                background-color: white; z-index:9999; font-size:14px;
                border:2px solid grey; border-radius: 5px; padding: 10px">
        <h4 style="margin-top:0">Skiløyper</h4>
        <p><span style="color:red">━━━</span> Alle løyper (unntatt backcountry)</p>
        <hr>
        <p style="font-size:12px; margin-top:10px;">
            💡 Bruk lag-kontrollen (øverst til høyre) for å filtrere på kommune
        </p>
        <p style="font-size:11px; color:#666; margin-top:5px;">
            Klikk på en løype for detaljer om preparering
        </p>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Lagre kart
    m.save(output_file)
    print(f"✓ Kart lagret: {output_file}")
    print(f"  Bruk lag-kontrollen i kartet for å filtrere på kommune")
    
    return m


def main():
    """Hovedfunksjon"""
    print("="*70)
    print("Hent skiløyper fra OpenStreetMap")
    print("="*70)
    print()
    
    # Faste filnavn for Gausdal
    geojson_file = 'Skiløyper_Gausdal.geojson'
    kart_file = 'Skiløyper_Gausdal.html'
    
    # Last inn kommunegrenser for rask lookup (valgfritt)
    kommuner_gdf = last_kommunegrenser('kommunegrenser_norge.geojson')
    print()
    
    # Område: Gausdal kommune
    # bbox = (min_lat, min_lon, max_lat, max_lon)
    print("📍 Område: Gausdal kommune")
    print("🔬 Henter data for testing med mindre datamengde\n")
    bbox = (61.05, 9.75, 61.55, 10.45)  # Gausdal kommune
    
    # Andre eksempler (kommenter ut Gausdal og aktiver ønsket område):
    # Innlandet fylke: bbox = (60.3, 9.0, 62.5, 12.5)
    # Trondheim: bbox = (63.35, 10.2, 63.50, 10.6)
    # Bergen: bbox = (60.3, 5.2, 60.5, 5.5)
    # Lillehammer: bbox = (61.0, 10.3, 61.2, 10.6)
    # Gausdal: bbox = (61.05, 9.75, 61.55, 10.45)
    # Hele Norge (ADVARSEL: tar LANG tid!): bbox = (58.0, 4.0, 71.0, 31.0)
    
    print()
    
    # 1. Last inn eksisterende data hvis den finnes
    existing_data = None
    if Path(geojson_file).exists():
        print(f"📂 Fant eksisterende fil: {geojson_file}")
        try:
            with open(geojson_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            existing_count = len(existing_data.get('features', []))
            print(f"   Inneholder {existing_count} eksisterende løyper")
            print()
        except Exception as e:
            print(f"   ⚠️  Kunne ikke lese eksisterende fil: {e}")
            existing_data = None
    
    # 2. Hent nye skiløyper fra OSM
    new_data = hent_skiløyper_osm(bbox, kommuner_gdf, timeout=600)
    
    if new_data:
        # 3. Merge og dedupliser
        if existing_data and existing_data.get('features'):
            print(f"\n🔄 Merger nye løyper med eksisterende...")
            
            # Bygg et set med eksisterende OSM IDer
            existing_ids = set()
            for feature in existing_data['features']:
                osm_id = feature['properties'].get('osm_id')
                if osm_id:
                    existing_ids.add(osm_id)
            
            # Legg til bare nye løyper (ikke duplikater)
            new_count = 0
            duplicate_count = 0
            for feature in new_data['features']:
                osm_id = feature['properties'].get('osm_id')
                if osm_id not in existing_ids:
                    existing_data['features'].append(feature)
                    existing_ids.add(osm_id)
                    new_count += 1
                else:
                    duplicate_count += 1
            
            print(f"   ✓ {new_count} nye løyper lagt til")
            print(f"   ✓ {duplicate_count} duplikater fjernet")
            print(f"   ✓ Totalt nå: {len(existing_data['features'])} løyper")
            
            merged_data = existing_data
        else:
            print(f"\n🆕 Oppretter ny fil med {len(new_data['features'])} løyper")
            merged_data = new_data
        
        # 4. Lagre GeoJSON med fast navn
        with open(geojson_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ GeoJSON lagret: {geojson_file}")
        
        # 5. Vis på kart
        vis_på_kart(merged_data, kart_file)
        
        print()
        print("="*70)
        print(f"✓ FERDIG! Åpne {kart_file} i nettleseren")
        print("="*70)
        
        # Vis statistikk
        print("\n📊 Statistikk:")
        grooming_count = {}
        for feature in merged_data['features']:
            grooming = feature['properties'].get('piste_grooming', 'unknown')
            grooming_count[grooming] = grooming_count.get(grooming, 0) + 1
        
        for grooming, count in sorted(grooming_count.items()):
            print(f"  {grooming}: {count} løyper")
    else:
        print("\n✗ Kunne ikke hente skiløyper")
        print("\n💡 Tips:")
        print("  - Reduser området (bbox)")
        print("  - Øk timeout-verdien")
        print("  - Prøv et annet område med flere skiløyper")


if __name__ == "__main__":
    main()
