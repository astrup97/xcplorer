"""
Last ned norske kommunegrenser fra Kartverket/Geonorge
Lagrer som GeoJSON for bruk i skiløype-kartlegging
"""

import requests
import json


def hent_kommunegrenser_kartverket():
    """
    Hent norske kommunegrenser fra Kartverket via WFS (Web Feature Service)
    Dette er mer pålitelig enn Overpass API for norske data
    """
    print("Henter norske kommunegrenser fra Kartverket/Geonorge...")
    print("Dette kan ta et par minutter...\n")
    
    # Kartverket WFS URL for administrative grenser
    # Bruker forenklet geometri for raskere nedlasting
    wfs_url = "https://wfs.geonorge.no/skwms1/wfs.adm_enheter_historic"
    
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'GetFeature',
        'typename': 'adm_enheter_historic:kommune',
        'outputFormat': 'application/json',
        'srsName': 'EPSG:4326'
    }
    
    try:
        print("Henter data fra Kartverket WFS...")
        response = requests.get(wfs_url, params=params, timeout=300)
        response.raise_for_status()
        geojson_data = response.json()
        
        print(f"✓ Hentet data fra Kartverket")
        
        # Forenkle og strukturer dataen
        features = []
        for feature in geojson_data.get('features', []):
            props = feature.get('properties', {})
            
            simplified_feature = {
                'type': 'Feature',
                'geometry': feature.get('geometry'),
                'properties': {
                    'kommune_nr': props.get('kommunenummer', props.get('objid', '')),
                    'kommune_navn': props.get('navn', props.get('kommunenavn', 'Ukjent')),
                    'fylke': props.get('fylkesnavn', ''),
                }
            }
            features.append(simplified_feature)
        
        print(f"✓ Prosessert {len(features)} kommuner")
        
        return {
            'type': 'FeatureCollection',
            'features': features
        }
        
    except requests.exceptions.Timeout:
        print(f"✗ Timeout - prøver alternativ metode...")
        return hent_kommunegrenser_alternativ()
    except Exception as e:
        print(f"✗ Feil med Kartverket WFS: {e}")
        print("Prøver alternativ metode...")
        return hent_kommunegrenser_alternativ()


def hent_kommunegrenser_alternativ():
    """
    Alternativ metode: Last ned fra pålitelige statiske kilder
    """
    print("\nPrøver alternative kilder...")
    
    # Liste over alternative kilder
    sources = [
        {
            'name': 'GitHub - Norge GeoJSON',
            'url': 'https://raw.githubusercontent.com/deldersveld/topojson/master/countries/norway/norway-new-counties.json'
        },
        {
            'name': 'Kartverket via GeoNorge API',
            'url': 'https://nedlasting.geonorge.no/api/codelists/administrativeenheter/kommune'
        }
    ]
    
    for source in sources:
        try:
            print(f"  Prøver: {source['name']}...")
            response = requests.get(source['url'], timeout=60)
            
            if response.status_code == 200:
                print(f"  ✓ Lastet ned fra {source['name']}")
                
                # Prøv å parse som JSON
                data = response.json()
                
                # Sjekk om det er TopoJSON (trenger konvertering)
                if 'type' in data and data['type'] == 'Topology':
                    print("  ⚠️  TopoJSON format - dette krever manuell konvertering")
                    continue
                
                # Hvis det er GeoJSON, returner det
                if 'type' in data and data['type'] == 'FeatureCollection':
                    features = []
                    for feature in data.get('features', []):
                        props = feature.get('properties', {})
                        
                        simplified_feature = {
                            'type': 'Feature',
                            'geometry': feature.get('geometry'),
                            'properties': {
                                'kommune_nr': str(props.get('KOMMUNENR', props.get('code', props.get('id', '')))),
                                'kommune_navn': props.get('NAME', props.get('name', props.get('navn', 'Ukjent'))),
                                'fylke': props.get('FYLKESNAVN', props.get('county', '')),
                            }
                        }
                        features.append(simplified_feature)
                    
                    if features:
                        print(f"  ✓ Prosessert {len(features)} kommuner")
                        return {
                            'type': 'FeatureCollection',
                            'features': features
                        }
        
        except Exception as e:
            print(f"  ✗ Feilet: {e}")
            continue
    
    # Hvis ingen kilder fungerte, lag en forenklet versjon med OSM for færre kommuner
    print("\n  Alle kilder feilet. Prøver med OSM for utvalgte kommuner...")
    return hent_utvalgte_kommuner_osm()


def hent_utvalgte_kommuner_osm():
    """
    Hent et utvalg av store norske kommuner fra OSM (raskere enn alle)
    Dekker de mest populære skiløype-områdene
    """
    # Viktige kommuner for skiløyper
    kommuner = [
        'Oslo', 'Lillehammer', 'Trondheim', 'Bergen', 'Tromsø',
        'Gausdal', 'Ringebu', 'Vågå', 'Lom', 'Sel', 'Nord-Fron', 'Sør-Fron',
        'Oppdal', 'Røros', 'Tynset', 'Tolga', 'Os', 'Engerdal',
        'Drammen', 'Kongsberg', 'Hønefoss', 'Gjøvik', 'Hamar', 'Elverum'
    ]
    
    print(f"  Henter {len(kommuner)} viktige skiløype-kommuner fra OSM...")
    
    features = []
    for kommune_navn in kommuner:
        try:
            # Bruk Nominatim for å hente kommune-grenser
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': f"{kommune_navn}, Norge",
                'format': 'geojson',
                'polygon_geojson': 1,
                'limit': 1
            }
            headers = {'User-Agent': 'SkiTrailMapper/1.0'}
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('features'):
                    feature = data['features'][0]
                    feature['properties'] = {
                        'kommune_nr': '',
                        'kommune_navn': kommune_navn,
                        'fylke': ''
                    }
                    features.append(feature)
                    print(f"    ✓ {kommune_navn}")
            
            # Rate limiting
            import time
            time.sleep(1.5)
            
        except:
            continue
    
    if features:
        print(f"  ✓ Hentet {len(features)} kommuner")
        return {
            'type': 'FeatureCollection',
            'features': features
        }
    
    return None


def main():
    """Hovedfunksjon"""
    output_file = 'kommunegrenser_norge.geojson'
    
    print("="*70)
    print("Last ned norske kommunegrenser")
    print("="*70)
    print()
    
    # Hent data fra Kartverket (primær metode)
    geojson = hent_kommunegrenser_kartverket()
    
    if geojson:
        # Lagre til fil
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Kommunegrenser lagret: {output_file}")
        print(f"   Størrelse: {len(json.dumps(geojson)) / 1024 / 1024:.1f} MB")
        print("\n✓ Nå kan du bruke denne filen i hent_skiløyper_osm.py")
        print("  for rask offline kommune-lookup!")
    else:
        print("\n✗ Kunne ikke hente kommunegrenser")
        print("\n💡 Tips:")
        print("  - Sjekk internettforbindelsen")
        print("  - Prøv igjen senere")
        print("  - Alternativt: Last ned manuelt fra geonorge.no")


if __name__ == "__main__":
    main()
