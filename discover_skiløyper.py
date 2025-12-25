"""
Discover skiløyper - Match GPX-spor mot skiløyper og vis discovery progress
"""

import json
import folium
from pathlib import Path
import math

# Prøv å importere avhengigheter
try:
    import gpxpy
    import gpxpy.gpx
except ImportError:
    print("⚠️  Mangler gpxpy - installer med: pip install gpxpy")
    exit(1)

try:
    from shapely.geometry import LineString, Point
    from shapely.ops import substring
except ImportError:
    print("⚠️  Mangler shapely - installer med: pip install shapely")
    exit(1)


def les_gpx(gpx_file):
    """
    Les GPX-fil og returner liste med koordinater [(lon, lat), ...]
    """
    print(f"📂 Leser GPX-fil: {gpx_file}")
    
    with open(gpx_file, 'r', encoding='utf-8') as f:
        gpx = gpxpy.parse(f)
    
    coordinates = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coordinates.append((point.longitude, point.latitude))
    
    print(f"   ✓ Hentet {len(coordinates)} GPS-punkter")
    return coordinates


def beregn_linje_lengde(linestring):
    """
    Beregn lengde av en LineString i meter (tilnærmet)
    Bruker Haversine-formel for å beregne avstand mellom punkter
    """
    def haversine(lon1, lat1, lon2, lat2):
        R = 6371000  # Jordens radius i meter
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    total = 0
    coords = list(linestring.coords)
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        total += haversine(lon1, lat1, lon2, lat2)
    
    return total


def segmenter_løype(linestring, segment_lengde=100):
    """
    Del en LineString i segmenter med gitt lengde (meter)
    Returnerer liste av LineString-segmenter
    """
    total_lengde = beregn_linje_lengde(linestring)
    antall_segmenter = max(1, int(total_lengde / segment_lengde))
    
    segmenter = []
    for i in range(antall_segmenter):
        # Bruk Shapely's substring for å få deler av linjen
        start_frac = i / antall_segmenter
        end_frac = (i + 1) / antall_segmenter
        
        try:
            segment = substring(linestring, start_frac, end_frac, normalized=True)
            segmenter.append(segment)
        except:
            continue
    
    return segmenter


def sjekk_segment_besøkt(segment, gpx_punkter, buffer_meter=50):
    """
    Sjekk om et segment er besøkt basert på GPX-punkter
    Returnerer True hvis noen GPX-punkt er innenfor buffer_meter fra segmentet
    
    buffer_meter tilsvarer omtrent denne grader for lat/lon:
    50m ≈ 0.00045 grader på breddegrad 60°N
    """
    buffer_degrees = buffer_meter / 111000  # Tilnærming: 1 grad ≈ 111km
    
    # Lag en buffer rundt segmentet
    buffered_segment = segment.buffer(buffer_degrees)
    
    # Sjekk om noen GPX-punkt er innenfor buffer
    for lon, lat in gpx_punkter:
        punkt = Point(lon, lat)
        if buffered_segment.contains(punkt):
            return True
    
    return False


def prosesser_løyper(geojson_file, gpx_file):
    """
    Prosesser skiløyper: segmenter og match mot GPX
    """
    print(f"\n{'='*70}")
    print(f"Prosesserer skiløyper")
    print(f"{'='*70}\n")
    
    # 1. Les skiløyper
    print(f"📂 Leser skiløyper: {geojson_file}")
    with open(geojson_file, 'r', encoding='utf-8') as f:
        skiløyper_data = json.load(f)
    
    antall_løyper = len(skiløyper_data['features'])
    print(f"   ✓ {antall_løyper} løyper lastet\n")
    
    # 2. Les GPX
    gpx_punkter = les_gpx(gpx_file)
    print()
    
    # 3. Segmenter og match
    print(f"🔧 Segmenterer løyper i 100m biter...")
    
    alle_segmenter = []
    total_lengde_meter = 0
    besøkt_lengde_meter = 0
    
    for feature in skiløyper_data['features']:
        coords = feature['geometry']['coordinates']
        linestring = LineString(coords)
        
        # Segmenter løypa
        segmenter = segmenter_løype(linestring, segment_lengde=100)
        
        for segment in segmenter:
            segment_lengde = beregn_linje_lengde(segment)
            total_lengde_meter += segment_lengde
            
            # Sjekk om segment er besøkt
            besøkt = sjekk_segment_besøkt(segment, gpx_punkter, buffer_meter=50)
            
            if besøkt:
                besøkt_lengde_meter += segment_lengde
            
            alle_segmenter.append({
                'geometry': segment,
                'besøkt': besøkt,
                'lengde': segment_lengde,
                'properties': feature['properties']
            })
    
    print(f"   ✓ {len(alle_segmenter)} segmenter opprettet")
    print(f"   ✓ Total lengde: {total_lengde_meter/1000:.2f} km")
    print(f"   ✓ Besøkt lengde: {besøkt_lengde_meter/1000:.2f} km")
    
    discovery_prosent = (besøkt_lengde_meter / total_lengde_meter * 100) if total_lengde_meter > 0 else 0
    print(f"   ✓ Discovery: {discovery_prosent:.1f}%\n")
    
    return {
        'segmenter': alle_segmenter,
        'gpx_punkter': gpx_punkter,
        'stats': {
            'total_km': total_lengde_meter / 1000,
            'besøkt_km': besøkt_lengde_meter / 1000,
            'discovery_prosent': discovery_prosent
        }
    }


def lag_kart(data, output_file='discovery_kart.html'):
    """
    Lag interaktivt kart med segmenterte løyper og GPX-spor
    """
    print(f"🗺️  Lager kart...")
    
    segmenter = data['segmenter']
    gpx_punkter = data['gpx_punkter']
    stats = data['stats']
    
    # Finn sentrum av kartet
    if gpx_punkter:
        center_lon = sum(p[0] for p in gpx_punkter) / len(gpx_punkter)
        center_lat = sum(p[1] for p in gpx_punkter) / len(gpx_punkter)
    else:
        center_lat, center_lon = 61.3, 10.1  # Gausdal
    
    # Opprett kart
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles='OpenStreetMap'
    )
    
    # Legg til løype-segmenter
    for segment in segmenter:
        coords = [(lat, lon) for lon, lat in segment['geometry'].coords]
        color = 'green' if segment['besøkt'] else 'red'
        
        folium.PolyLine(
            coords,
            color=color,
            weight=5,
            opacity=0.8
        ).add_to(m)
    
    # Legg til GPX-spor (tynn blå linje)
    gpx_coords = [(lat, lon) for lon, lat in gpx_punkter]
    folium.PolyLine(
        gpx_coords,
        color='blue',
        weight=2,
        opacity=0.6,
        popup='Din rute'
    ).add_to(m)
    
    # Legg til leaderboard og statistikk
    leaderboard_html = f"""
    <div style="position: fixed; 
                top: 10px; left: 10px; width: 280px; 
                background-color: white; z-index:9999; 
                border:3px solid #2E7D32; border-radius: 10px; padding: 15px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h3 style="margin-top:0; color:#2E7D32; border-bottom: 2px solid #2E7D32; padding-bottom: 10px;">
            🏆 Discovery Leaderboard
        </h3>
        
        <div style="background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%); 
                    color: white; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <span style="font-size: 24px; margin-right: 10px;">🥇</span>
                <span style="font-size: 20px; font-weight: bold;">Ulrik</span>
            </div>
            <div style="font-size: 32px; font-weight: bold; text-align: center; margin: 10px 0;">
                {stats['discovery_prosent']:.1f}%
            </div>
            <div style="font-size: 14px; opacity: 0.9; text-align: center;">
                {stats['besøkt_km']:.2f} av {stats['total_km']:.2f} km
            </div>
        </div>
        
        <hr style="border: 1px solid #e0e0e0;">
        
        <div style="font-size: 12px; color: #666; margin-top: 10px;">
            <p style="margin: 5px 0;">
                <span style="display: inline-block; width: 15px; height: 3px; background: green; margin-right: 5px;"></span>
                Besøkt ({len([s for s in segmenter if s['besøkt']])} segmenter)
            </p>
            <p style="margin: 5px 0;">
                <span style="display: inline-block; width: 15px; height: 3px; background: red; margin-right: 5px;"></span>
                Ikke besøkt ({len([s for s in segmenter if not s['besøkt']])} segmenter)
            </p>
            <p style="margin: 5px 0;">
                <span style="display: inline-block; width: 15px; height: 2px; background: blue; margin-right: 5px;"></span>
                Din rute
            </p>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(leaderboard_html))
    
    # Lagre kart
    m.save(output_file)
    print(f"   ✓ Kart lagret: {output_file}\n")
    
    return m


def main():
    """Hovedfunksjon"""
    print("="*70)
    print("🎿 Discover Skiløyper - Gausdal Kommune")
    print("="*70)
    print()
    
    # Filer
    geojson_file = 'Skiløyper_Gausdal.geojson'
    gpx_file = r'C:\Users\no-ular\Downloads\Utaskjærs_til_Fykse_m_petz.gpx'
    output_file = 'discovery_kart_gausdal.html'
    
    # Sjekk at filer eksisterer
    if not Path(geojson_file).exists():
        print(f"❌ Finner ikke: {geojson_file}")
        print(f"   Kjør først: python hent_skiløyper_osm.py")
        return
    
    if not Path(gpx_file).exists():
        print(f"❌ Finner ikke: {gpx_file}")
        return
    
    # Prosesser
    data = prosesser_løyper(geojson_file, gpx_file)
    
    # Lag kart
    lag_kart(data, output_file)
    
    # Vis resultat
    print("="*70)
    print("✅ FERDIG!")
    print("="*70)
    print(f"\n🎉 Gratulerer, Ulrik!")
    print(f"   Du har discoveret {data['stats']['discovery_prosent']:.1f}% av skiløypenettet")
    print(f"   ({data['stats']['besøkt_km']:.2f} av {data['stats']['total_km']:.2f} km)")
    print(f"\n📂 Åpne {output_file} for å se resultatet!")


if __name__ == "__main__":
    main()
