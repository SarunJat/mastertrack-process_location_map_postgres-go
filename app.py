import psycopg2
import geopandas as gpd
from shapely.geometry import Point
from psycopg2.extras import execute_batch
from geopy.distance import geodesic
import time
import schedule
import json
import sys


# --- Application Version ---
APP_VERSION = "1.1.4" # Define the application version here

def get_app_version():
    """Returns the application version string."""
    return APP_VERSION
# -------------------------
# postgresql://postgres:[YOUR-PASSWORD]@db.ufstjzowpihgerwuvmlt.supabase.co:5432/postgres
# Configuration
DB_CONFIG = {
    'dbname': 'postgres',
    'user': 'postgres.ufstjzowpihgerwuvmlt',
    'password': 'MtTrack@Gps!1234',
    'host': 'aws-0-ap-southeast-1.pooler.supabase.com',
    'port': '6543',
}
# Global variable to store settings
SETTINGS = {}

def write_log(message):
    """Writes a log message to a file."""
    log_file = 'app.log'
    try:
        with open(log_file, 'a') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except Exception as e:
        print(f"Error writing to log file: {e}")

def load_settings(config_file='settings.json'):
    """Load settings from JSON file into global SETTINGS variable"""
    global SETTINGS
    try:
        with open(config_file, 'r') as f:
            SETTINGS = json.load(f)
        print("Settings loaded successfully")
        write_log("Settings loaded successfully")
    except FileNotFoundError:
        print(f"Error: Config file '{config_file}' not found")
        write_log(f"Error: Config file '{config_file}' not found")
        input("Press Enter to exit...")  # Pause to allow viewing the error
        sys.exit(1)
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in settings file")
        write_log("Error: Invalid JSON format in settings file")
        input("Press Enter to exit...")  # Pause to allow viewing the error
        sys.exit(1)

def connect_setting_db():
    # Connect to the database using the loaded configuration
    return psycopg2.connect(**DB_CONFIG)

def connect_db():
    # Load the database configuration from the JSON file
    with open('db_config.json', 'r') as file:
        db_config = json.load(file)
    
    # Connect to the database using the loaded configuration
    return psycopg2.connect(**db_config)

# Global variable to store location data
location_cache = []

def load_shapefile(file_path, encoding="utf-8", crs_epsg=4326):
    """
    Load a shapefile, set its CRS if missing, and return the GeoDataFrame.
    """
    try:
        write_log(f"Loading shapefile: {file_path}")
        gdf = gpd.read_file(file_path, encoding=encoding)
        if gdf.crs is None:
            gdf.set_crs(epsg=crs_epsg, inplace=True)
        return gdf
    except FileNotFoundError:
        error_msg = f"Error: Shapefile not found: {file_path}"
        write_log(error_msg)
        print(time.strftime('%Y-%m-%d %H:%M:%S'), error_msg)
        # Return an empty GeoDataFrame with the right structure
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{crs_epsg}")
    except Exception as e:
        error_msg = f"Error loading shapefile {file_path}: {str(e)}"
        write_log(error_msg)
        print(time.strftime('%Y-%m-%d %H:%M:%S'), error_msg)
        # Return an empty GeoDataFrame with the right structure
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{crs_epsg}")

def load_location_cache():
    """Load location data into memory."""
    global location_cache
    location_cache = []

    with connect_setting_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT customer_id, location_desc, latitude, longitude, radius
                FROM location
            """)
            location_cache = cur.fetchall()
    print(time.strftime('%Y-%m-%d %H:%M:%S'),f"Mark location all {len(location_cache)} records loaded.")

def find_layer_by_point(gps_point, layer_gdf, name_field, is_province=False):
    """
    Perform a spatial join to find which polygon layer contains the GPS point.
    
    Parameters:
        gps_point (GeoDataFrame): The GeoDataFrame containing the GPS point.
        layer_gdf (GeoDataFrame): The polygon layer to search.
        name_field (str): The attribute field name to extract (e.g., "NAME_THAI").
        is_province (bool): If True, prepend 'จ.' to the matched name.
    
    Returns:
        str: The value of the `name_field` for the polygon containing the GPS point,
             with some keywords replaced (ตำบล -> ต., เขต -> ข., จังหวัด -> จ.).
             Also, if `is_province` is True, prepend 'จ.'.
    """
    result = gpd.sjoin(gps_point, layer_gdf, how="left", predicate="within")
    if not result.empty:
        # Get the name from the specified field
        location_name = str(result.iloc[0].get(name_field, f"Unknown {name_field}"))
        
        # If this is a province layer, add "จ." prefix
        if is_province:
            location_name = location_name.replace('จังหวัด', 'จ.')
            if not location_name.startswith('จ.'):
                location_name = f"จ.{location_name}"
        # Perform the replacements
        location_name = (location_name.replace('ตำบล', 'ต.')
                         .replace('แขวง', 'ต.')
                         .replace('เขต', 'อ.')
                         .replace('อำเภอ', 'อ.')
                         .replace('แขวง', 'ต.'))
        return location_name
    
    return f"Unknown {name_field}"

def search_location_by_point(latitude, longitude, layers):
    """
    Search multiple layers for a GPS point and return concatenated results.

    Parameters:
        latitude (float): The latitude of the GPS point.
        longitude (float): The longitude of the GPS point.
        layers (list of dict): List of dictionaries, each representing a layer, with:
            - 'gdf': GeoDataFrame for the layer.
            - 'name_field': The attribute field name for the layer.

    Returns:
        str: Concatenated names from all layers that contain the point.
    """
    # Create GeoDataFrame for the GPS point
    gps_point = gpd.GeoDataFrame(
        [{'geometry': Point(longitude, latitude)}],
        crs="EPSG:4326"
    )
    
    # Search each layer
    results = []
    for layer in layers:
        name = find_layer_by_point(gps_point, layer['gdf'], layer['name_field'],layer['is_province'])
        results.append(name)
    
    return " ".join(results)

def is_valid_coordinate(lat, lon):
    """Validate latitude and longitude ranges."""
    return -90 <= lat <= 90 and -180 <= lon <= 180

def find_location(lat, lon, gps_customer_id):
    """Find location within the radius for given latitude, longitude, and customer_id."""
    if not is_valid_coordinate(lat, lon):
        print(f"Invalid coordinates: latitude={lat}, longitude={lon}")
        return ""  # Skip invalid coordinates

    for loc in location_cache:
        loc_customer_id, loc_desc, loc_lat, loc_lon, loc_radius = loc[0], loc[1], loc[2], loc[3], loc[4]
        # Ensure customer_id matches
        if loc_customer_id == gps_customer_id:
            if is_valid_coordinate(loc_lat, loc_lon):  # Validate cached location
                distance = geodesic((lat, lon), (loc_lat, loc_lon)).meters
                if distance <= loc_radius:
                    return loc_desc  # Return location_desc
    return ""  # Return empty string if no match found

def process_gps_detail():
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Start process_gps_detail')
    write_log("Start process_gps_detail")
    """Process GPS details and update locations in batches of 200 until 1,000 records are processed."""
     # Step 1: Load shapefiles
    write_log("Loading shapefiles")
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Loading shapefiles')
    
    countries_gdf = load_shapefile("data_map3/Th_Country_region.shp", encoding="TIS-620")
    
    provinces_gdf = load_shapefile("data_map3/Th_Province_region.shp", encoding="TIS-620")
    
    amphur_gdf = load_shapefile("data_map3/Th_Amphoe_region.shp", encoding="TIS-620")
    
    tambon_gdf = load_shapefile("data_map3/Th_Tambon_region.shp", encoding="TIS-620")       
    
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'Shape Files : Loaded')
    write_log("Shape Files : Loaded")
    # Step 2: Define layers for searching
    layers = [
        {'gdf': tambon_gdf, 'name_field': 'NAME_THAI','is_province':False},
        {'gdf': amphur_gdf, 'name_field': 'NAME_THAI','is_province':False},
        {'gdf': provinces_gdf, 'name_field': 'NAME_THAI','is_province':True},
        {'gdf': countries_gdf, 'name_field': 'NAME_THAI','is_province':False},   # Country layer
    ]
    try:
        with connect_db() as conn:
            write_log("Connected to database")
            print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Connected to database')
            with conn.cursor() as cur:
                # Query up to 1,000 records with specified conditions
                limit_records = SETTINGS.get("limit_records", 1500)
                if SETTINGS:
                    print(f"Direct access example: Limit is {SETTINGS['limit_records']}")
                cur.execute(f"""
                    SELECT customer_id, mobile_id, event_datetime, event_status, latitude, longitude
                    FROM gps_detail
                    WHERE location IS NULL 
                      AND event_status IN ('91', '92', '44')
                    ORDER BY customer_id,mobile_id,event_datetime DESC
                    LIMIT {limit_records}
                """)
                rows = cur.fetchall()
                total_records = len(rows)
                print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {total_records} records to process.")
                write_log(f"Fetched {total_records} records to process.")
                if total_records == 0:
                    print("No records to process.")
                    return

                for i in range(0, total_records, 500):  # Process in chunks of 200
                    updates = []
                    batch = rows[i:i+500]  # Get the next batch of 200 records
                    for row in batch:
                        customer_id, mobile_id, event_datetime, event_status, latitude, longitude = row
                        if latitude is not None and longitude is not None:
                            location_desc = find_location(latitude, longitude, customer_id)
                            if location_desc == "":
                                location_desc = search_location_by_point(latitude, longitude, layers)
                            updates.append((location_desc, customer_id, mobile_id, event_datetime, event_status))

                    # Perform the update for the current batch
                    execute_batch(
                        cur,
                        """
                        UPDATE gps_detail
                        SET location = %s
                        WHERE customer_id = %s AND mobile_id = %s AND event_datetime = %s AND event_status = %s
                        """,
                        updates
                    )
                    conn.commit()  # Commit after each batch
                    print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Updated {len(updates)} records in this batch.")
                print(time.strftime('%Y-%m-%d %H:%M:%S')," All records processed for this cycle.")

    except Exception as e:
        print(f"Error query processing GPS detail process_gps_detail: {e}")
        write_log(f"Error query processing GPS detail process_gps_detail: {e}")
    
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'End process_gps_detail')    

def process_gps_detail_all_position(customer_id='3150'):
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'Start process_gps_detail_full_position',customer_id)
    write_log(f"Start process_gps_detail_full_position {customer_id}")

    try:
        with connect_db() as conn:
            with conn.cursor() as cur:
                # Query up to 1,000 records with specified conditions
                limit_records = SETTINGS.get("limit_records", 1500)
                total_records = 0
                if SETTINGS:
                    print(f"Direct access example: Limit is {SETTINGS['limit_records']}")
                try:
                  cur.execute(f"""
                    SELECT customer_id, mobile_id, event_datetime, event_status, latitude, longitude
                    FROM gps_detail
                    WHERE customer_id=%s AND location IS NULL                                  
                    LIMIT {limit_records}
                  """, (customer_id,))
                  rows = cur.fetchall()
                  total_records = len(rows)
                  print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {total_records} records to process.")
                except Exception as e:
                    if "canceling statement due to statement timeout" in str(e):
                        write_log("Query timeout occurred, consider reducing limit_records in settings.json")
                        if "limit_records" in SETTINGS and limit_records > 500:
                            SETTINGS["limit_records"] = max(500, limit_records // 2)
                            write_log(f"Automatically reduced limit_records to {limit_records}")
                    else:
                        write_log(f"Fetched {len(rows)} records to process.")   
                        print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {len(rows)} records to process.")
                        exception_msg = f"Error fetching records: {e}"
                        write_log(exception_msg)                 
                        raise

                if total_records == 0:
                    print("No records to process.")
                    return

                for i in range(0, total_records, 500):  # Process in chunks of 200
                    updates = []
                    batch = rows[i:i+500]  # Get the next batch of 200 records
                    for row in batch:
                        customer_id, mobile_id, event_datetime, event_status, latitude, longitude = row
                        if latitude is not None and longitude is not None:
                            location_desc = find_location(latitude, longitude, customer_id)
                            updates.append((location_desc, customer_id, mobile_id, event_datetime, event_status))

                    # Perform the update for the current batch
                    execute_batch(
                        cur,
                        """
                        UPDATE gps_detail
                        SET location = %s
                        WHERE customer_id = %s AND mobile_id = %s AND event_datetime = %s AND event_status = %s
                        """,
                        updates
                    )
                    conn.commit()  # Commit after each batch
                    print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Updated {len(updates)} records in this batch.")
                print(time.strftime('%Y-%m-%d %H:%M:%S')," All records processed for this cycle.")

    except Exception as e:
        print(f"Error query processing GPS detail process_gps_detail_full_position: {e}")
        write_log(f"Error query processing GPS detail process_gps_detail_full_position: {e}")
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'End process_gps_detail_full_position',customer_id)    

def process_gps_tasks():
    write_log("Starting process_gps_tasks")
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Start process_gps_tasks')
    process_gps_detail()
    write_log("Finished process_gps_detail")
    process_gps_detail_all_position("3150")
    process_gps_detail_all_position("3164")

def main():
    try:
        print(f"--- MasterTrack Location Processor v{get_app_version()} ---")
        
        write_log("Starting application")
        load_settings()
        write_log("Settings loaded")
        
        # Load location cache every 4 hours
        schedule.every(SETTINGS.get("loop_getlocation_every_hours", 4)).hours.do(load_location_cache)

        # Process GPS details every 5 minutes
        schedule.every(SETTINGS.get("loop_process_every_seconds", 4)).seconds.do(process_gps_tasks)

        # Initial load of location cache
        load_location_cache()
        print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Initial load of location cache')
        write_log("Initial load of location cache")

        while True:
            schedule.run_pending()
            time.sleep(1)  # Avoid busy waiting
    except Exception as e:
        print(f"Error: {e}")
        write_log(f"Unhandled exception occurred in the main function: {e}")
        input("Press Enter to exit...")  # Pause to allow viewing the error

if __name__ == "__main__":
    main()