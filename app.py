import psycopg2
import geopandas as gpd
from shapely.geometry import Point
from psycopg2.extras import execute_batch
from geopy.distance import geodesic
import time
import schedule
import json
import logging # Import logging
import sys # Needed for sys.executable

# --- Application Version ---
APP_VERSION = "1.1.0" # Define the application version here

def get_app_version():
    """Returns the application version string."""
    return APP_VERSION
# -------------------------

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

def load_settings(config_file='settings.json'):
    
    # logging.info(f"--- MasterTrack Location Processor v{get_app_version()} ---") # Use logging
    

    """Load settings from JSON file into global SETTINGS variable"""
    global SETTINGS
    try:
        with open(config_file, 'r') as f:
            SETTINGS = json.load(f)
        print("Settings loaded successfully")
        logging.info("Settings loaded successfully") # Use logging
    except FileNotFoundError:
        print(f"Error: Config file '{config_file}' not found")
        logging.error(f"Error: Config file '{config_file}' not found") # Use logging
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in settings file")
        logging.error("Error: Invalid JSON format in settings file")

def connect_setting_db():
    # return psycopg2.connect(**DB_CONFIG)
    
    # Connect to the database using the loaded configuration
    return psycopg2.connect(**DB_CONFIG)

def connect_db():
    # return psycopg2.connect(**DB_CONFIG)
     # Load the database configuration from the JSON file
    with open('db_config.json', 'r') as file:
        db_config = json.load(file)
    
    # Connect to the database using the loaded configuration
    return psycopg2.connect(**db_config)

# Global variable to store location data
location_cache = []

# Function to load and ensure CRS is set
# def load_shapefile(file_path, encoding="utf-8", crs_epsg=4326):
#     """
#     Load a shapefile, set its CRS if missing, and return the GeoDataFrame.
#     """
#     logging.info(f"Loading shapefile: {file_path}") # Use logging
#     print(time.strftime('%Y-%m-%d %H:%M:%S'), f"Loading shapefile: {file_path}")
#     gdf = gpd.read_file(file_path, encoding=encoding)
#     if gdf.crs is None:
#         gdf.set_crs(epsg=crs_epsg, inplace=True)
#     return gdf
def load_shapefile(file_path, encoding="utf-8", crs_epsg=4326):
    """
    Load a shapefile, set its CRS if missing, and return the GeoDataFrame.
    """
    try:
        logging.info(f"Loading shapefile: {file_path}")
        # print(time.strftime('%Y-%m-%d %H:%M:%S'), f"Loading shapefile: {file_path}")
        gdf = gpd.read_file(file_path, encoding=encoding)
        if gdf.crs is None:
            gdf.set_crs(epsg=crs_epsg, inplace=True)
        return gdf
    except FileNotFoundError:
        error_msg = f"Error: Shapefile not found: {file_path}"
        logging.error(error_msg)
        print(time.strftime('%Y-%m-%d %H:%M:%S'), error_msg)
        # Return an empty GeoDataFrame with the right structure
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{crs_epsg}")
    except Exception as e:
        error_msg = f"Error loading shapefile {file_path}: {str(e)}"
        logging.error(error_msg)
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
    print(time.strftime('%Y-%m-%d %H:%M:%S'),f"Mark location {len(location_cache)} records loaded.")


def setup_logging():
    """Sets up logging to file and console."""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    log_file = 'app.log' # Log file will be created in the same directory as the exe

    # File Handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO) # Log INFO level and above to file

    # Console Handler (optional, but good for seeing output when run manually)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO) # Show INFO level and above on console

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # Set root logger level
    logger.addHandler(file_handler)
    # logger.addHandler(console_handler) # Uncomment to also see logs in console if it stays open

    # Redirect print statements to logging (optional)
    # sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO)
    # sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR)


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
        # if location_name == 'ไทย':
        #     location_name = ''
        # Perform the replacements
        location_name = (location_name.replace('ตำบล', 'ต.')
                         .replace('แขวง', 'ต.')
                         .replace('เขต', 'อ.')
                         .replace('อำเภอ', 'อ.')
                         .replace('แขวง', 'ต.'))
        return location_name
    
    return f"Unknown {name_field}"


# Function to search for a GPS point across multiple layers
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
    """Process GPS details and update locations in batches of 200 until 1,000 records are processed."""
     # Step 1: Load shapefiles
    logging.info("Loading shapefiles") # Use logging
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Loading shapefiles')
    
    countries_gdf = load_shapefile("data_map3/Th_Country_region.shp", encoding="TIS-620")
    
    provinces_gdf = load_shapefile("data_map3/Th_Province_region.shp", encoding="TIS-620")
    
    amphur_gdf = load_shapefile("data_map3/Th_Amphoe_region.shp", encoding="TIS-620")
    
    tambon_gdf = load_shapefile("data_map3/Th_Tambon_region.shp", encoding="TIS-620")       
    
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'Shape Files : Loaded')
    logging.info("Shape Files : Loaded") # Use logging
    # Step 2: Define layers for searching
    layers = [
        {'gdf': tambon_gdf, 'name_field': 'NAME_THAI','is_province':False},
        {'gdf': amphur_gdf, 'name_field': 'NAME_THAI','is_province':False},
        {'gdf': provinces_gdf, 'name_field': 'NAME_THAI','is_province':True},
        {'gdf': countries_gdf, 'name_field': 'NAME_THAI','is_province':False},   # Country layer
         # Province layer
          # Amphur layer
         # Tambon layer
    ]
    try:
        with connect_db() as conn:
            logging.info("Connected to database") # Use logging
            print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Connected to database')
            with conn.cursor() as cur:
                # Query up to 1,000 records with specified conditions
                limit_records = SETTINGS.get("limit_records", 1500)
                if SETTINGS:
                    print(f"Direct access example: Limit is {SETTINGS['limit_records']}")
                    # print(limit_records)
                cur.execute(f"""
                    SELECT customer_id, mobile_id, event_datetime, event_status, latitude, longitude
                    FROM gps_detail
                    WHERE location IS NULL 
                      AND event_status IN ('91', '92', '44')
                    ORDER BY customer_id,mobile_id,event_datetime DESC
                    LIMIT {limit_records}
                """)
                rows = cur.fetchall()
                # logging.info(f"Fetched {len(rows)} records to process.") # Use logging
                # print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {len(rows)} records to process.")
                # Process the records in batches of 200
                total_records = len(rows)
                print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {total_records} records to process.")
                logging.info(f"Fetched {total_records} records to process.") # Use logging
                if total_records == 0:
                    # conn.close()
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
                                # print(f"Found location from shp map: {location_desc}")
                            # print(f"Found location: {location_desc}")
                             # 1) Convert from CP874 (WIN874) to valid UTF-8
                            # try: 
                            #     location_desc_utf8 = location_desc.encode("tis-620", errors="replace").decode("utf-8", errors="replace")
                            #     # cp874
                            #     print(location_desc_utf8)
                            # except UnicodeError:
                            #      # If an unexpected decode error occurs, fallback or skip
                            #     location_desc_utf8 = location_desc
        
                            # # 2) Append the UTF-8 cleaned data
                            # updates.append((location_desc_utf8, customer_id, mobile_id, event_datetime, event_status))
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
                # cur.close()    
                # conn.close()
                print(time.strftime('%Y-%m-%d %H:%M:%S')," All records processed for this cycle.")

    except Exception as e:
        # conn.close()
        # print(f"Error processing GPS detail: {e}")
        print(f"Error query processing GPS detail process_gps_detail: {e}")
        logging.exception(f"Error query processing GPS detail process_gps_detail: {e}") # Use logging
        # countries_gdf.close()
        # provinces_gdf.close()
        # amphur_gdf.close()
        # tambon_gdf.close()
    
    # countries_gdf.close()
    # provinces_gdf.close()
    # amphur_gdf.close()
    # tambon_gdf.close()    
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'End process_gps_detail')    


def process_gps_detail_full_position(customer_id='3150'):
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'Start process_gps_detail_full_position',customer_id)

    try:
        with connect_db() as conn:
            with conn.cursor() as cur:
                # Query up to 1,000 records with specified conditions
                limit_records = SETTINGS.get("limit_records", 1500)
                total_records = 0
                if SETTINGS:
                    print(f"Direct access example: Limit is {SETTINGS['limit_records']}")
                    # print(limit_records)
                try:
                  cur.execute(f"""
                    SELECT customer_id, mobile_id, event_datetime, event_status, latitude, longitude
                    FROM gps_detail
                    WHERE customer_id=%s AND location IS NULL                 
                    LIMIT {limit_records}
                  """, (customer_id,))
                  rows = cur.fetchall()
                #   print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {len(rows)} records to process.")
                  # Process the records in batches of 200
                  total_records = len(rows)
                  print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {total_records} records to process.")
                except Exception as e:
                    if "canceling statement due to statement timeout" in str(e):
                        logging.warning("Query timeout occurred, consider reducing limit_records in settings.json")
                        # Reduce the limit for the next run
                        if "limit_records" in SETTINGS and limit_records > 500:
                            SETTINGS["limit_records"] = max(500, limit_records // 2)
                            logging.info(f"Automatically reduced limit_records to {limit_records}")
                    else:
                        logging.info(f"Fetched {len(rows)} records to process.") # Use logging   
                        print(time.strftime('%Y-%m-%d %H:%M:%S'), f" Fetched {len(rows)} records to process.")
                        exception_msg = f"Error fetching records: {e}"
                        logging.error(exception_msg) # Use logging                 
                        raise  # Re-raise the exception if it's not a timeout
                 
                

                if total_records == 0:
                    # conn.close()
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
                # cur.close()    
                # conn.close()
                print(time.strftime('%Y-%m-%d %H:%M:%S')," All records processed for this cycle.")

    except Exception as e:
        # conn.close()
        print(f"Error query processing GPS detail process_gps_detail_full_position: {e}")
        logging.exception(f"Error query processing GPS detail process_gps_detail_full_position: {e}") # Use logging
    print(time.strftime('%Y-%m-%d %H:%M:%S'),'End process_gps_detail_full_position',customer_id)    
               
def process_gps_tasks():
    # First, process GPS details
    logging.info("Starting process_gps_tasks")
    print(time.strftime('%Y-%m-%d %H:%M:%S'), 'Start process_gps_tasks')
    process_gps_detail()
    logging.info("Finished process_gps_detail")
    # Then, process GPS details with full position
    process_gps_detail_full_position("3150")
    process_gps_detail_full_position("3164")
    

def main():
     # Print the version first
    print(f"--- MasterTrack Location Processor v{get_app_version()} ---")
    setup_logging()
    load_settings()
    # Load location cache every 4 hours
    schedule.every(SETTINGS.get("loop_getlocation_every_hours", 4)).hours.do(load_location_cache)

    # Process GPS details every 5 minutes
    schedule.every(SETTINGS.get("loop_process_every_seconds", 4)).seconds.do(process_gps_tasks)
    # schedule.every(1).minutes.do(lambda: (process_gps_detail(), process_gps_detail_3150_mark_olny()))
    # schedule.every(1).minutes.do(process_gps_detail_3150_mark_olny)

    # Initial load of location cache
    load_location_cache()

    while True:
        schedule.run_pending()
        # Uncomment the sleep statement to avoid busy waiting
        # time.sleep(1)

if __name__ == "__main__":
    main()